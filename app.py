from flask import Flask, render_template, request, url_for, redirect, flash, jsonify, abort, send_file
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import hashlib
import io
import tempfile
import atexit
from xml.sax.saxutils import escape
from werkzeug.utils import secure_filename
import time
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from flask_mail import Mail
from flask_migrate import Migrate
from flask_login import LoginManager, login_required, login_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_restful import Api, Resource
import logging
from flask_caching import Cache
from cachelib import SimpleCache
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import DevelopmentConfig, ProductionConfig
from models import db, User
from github_client import GitHubAPIError, GitHubClient
from github_webhooks import verify_github_signature
from external_http import request_with_retries
from routes.main import main
from routes.auth import auth
from whatsapp import CallMeBotProvider
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from scheduler import PostgresJobScheduler
from link_checker import check_link
from screenshot_provider import (
    ScreenshotOneProvider,
    ScreenshotQuotaExceeded,
    create_fallback_card,
    normalize_webp,
)

app = Flask(__name__)
production = os.environ.get('RENDER', '').lower() == 'true'
app.config.from_object(ProductionConfig if production else DevelopmentConfig)
if production and not os.environ.get('SECRET_KEY'):
    raise RuntimeError('SECRET_KEY must be configured in production.')

# ================== DATABASE CONFIGURATION ==================
DATABASE_URL = os.environ.get("DATABASE_URL", app.config.get("SQLALCHEMY_DATABASE_URI", ""))
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate = Migrate(app, db)

mail = Mail(app)
app.config['MAIL_TIMEOUT'] = 10

ADMIN_USERNAME = app.config['ADMIN_USERNAME']
ADMIN_PASSWORD = app.config['ADMIN_PASSWORD']

login_manager = LoginManager(app)
login_manager.login_view = "auth.admin_login"

api = Api(app)
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})
github_api_cache = SimpleCache(default_timeout=600)
CV_PDF_PATH = os.path.join(app.root_path, 'static', 'files', 'Al-ameen_cv.pdf')
_cv_cache_hash = None
contact_alert_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='contact-alerts')
csrf = CSRFProtect(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["20000 per day", "5000 per hour"]
)

# ================== BLUEPRINTS ==================
app.register_blueprint(main)
app.register_blueprint(auth, url_prefix='/auth')
app.view_functions['auth.admin_login'] = limiter.limit('5 per minute')(app.view_functions['auth.admin_login'])

# ================== UPLOAD CONFIGURATION ==================
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename, file_type='image'):
    if '.' not in filename:
        return False
    if filename.count('.') > 1:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if file_type == 'image':
        return ext in {'png', 'jpg', 'jpeg', 'gif'}
    else:
        return ext == 'pdf'


# ================== DATABASE HELPER ==================
def get_db_connection():
    max_retries = 3
    retry_delay = 1
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except psycopg2.Error as e:
            if attempt == max_retries - 1:
                print(f"Failed to connect to database after {max_retries} attempts: {e}")
                raise
            print(f"Database connection attempt {attempt + 1} failed. Retrying...")
            time.sleep(retry_delay)
    return None


def ensure_db_schema():
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        if DATABASE_URL.startswith('sqlite'):
            cursor.execute("CREATE TABLE IF NOT EXISTS site_content (id INTEGER PRIMARY KEY AUTOINCREMENT, section_name VARCHAR(100), title VARCHAR(255), content TEXT, file VARCHAR(255))")
            cursor.execute("CREATE TABLE IF NOT EXISTS skills (id INTEGER PRIMARY KEY AUTOINCREMENT, category VARCHAR(100) NOT NULL, name VARCHAR(100) NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS contact_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(255) NOT NULL, email VARCHAR(255) NOT NULL, subject VARCHAR(255), message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cursor.execute("CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, title VARCHAR(150) NOT NULL, description TEXT NOT NULL, link VARCHAR(255), image VARCHAR(255), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username VARCHAR(80) UNIQUE NOT NULL, email VARCHAR(120) UNIQUE NOT NULL, password VARCHAR(200) NOT NULL)")
        else:
            cursor.execute("CREATE TABLE IF NOT EXISTS site_content (id SERIAL PRIMARY KEY, section_name VARCHAR(100), title VARCHAR(255), content TEXT, file VARCHAR(255))")
            cursor.execute("CREATE TABLE IF NOT EXISTS skills (id SERIAL PRIMARY KEY, category VARCHAR(100) NOT NULL, name VARCHAR(100) NOT NULL)")
            cursor.execute("CREATE TABLE IF NOT EXISTS contact_messages (id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, email VARCHAR(255) NOT NULL, subject VARCHAR(255), message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cursor.execute("CREATE TABLE IF NOT EXISTS projects (id SERIAL PRIMARY KEY, title VARCHAR(150) NOT NULL, description TEXT NOT NULL, link VARCHAR(255), image VARCHAR(255), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL, email VARCHAR(120) UNIQUE NOT NULL, password VARCHAR(200) NOT NULL)")

        conn.commit()
        return True
    except psycopg2.Error as e:
        print(f"Error creating schema: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


def ensure_default_admin_user():
    try:
        with app.app_context():
            username = app.config.get('ADMIN_USERNAME', 'admin')
            password = app.config.get('ADMIN_PASSWORD', '')
            if not username or not password:
                return False

            user = User.query.filter_by(username=username).first()
            if user is None:
                user = User(
                    username=username,
                    email=f'{username}@local.dev',
                    password=generate_password_hash(password)
                )
                db.session.add(user)
                db.session.commit()
                return True

            if not check_password_hash(user.password, password):
                user.password = generate_password_hash(password)
                db.session.commit()
            return True
    except Exception as exc:
        print(f"Error ensuring default admin user: {exc}")
        return False


ensure_db_schema()
ensure_default_admin_user()


def get_content_from_db():
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM site_content")
        rows = cursor.fetchall()
        content = {}
        for row in rows:
            content[row['section_name']] = {
                "id": row['id'],
                "section_name": row['section_name'],
                "title": row['title'] or '',
                "content": row['content'] or '',
                "file": row['file'] or ''
            }
        return content
    except psycopg2.Error as e:
        print(f"Error getting content: {e}")
        return {}
    finally:
        cursor.close()
        conn.close()


def get_service_entries(content):
    services = []
    for section_name, service in content.items():
        match = re.fullmatch(r'service_(\d+)', section_name)
        if match and service.get('title'):
            services.append({**service, 'index': int(match.group(1))})
    return sorted(services, key=lambda service: service['index'])


def get_projects():
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM projects WHERE is_visible = TRUE ORDER BY is_pinned DESC, sort_order, CASE WHEN last_pushed_at IS NULL THEN 1 ELSE 0 END, last_pushed_at DESC, created_at DESC")
        projects = [dict(row) for row in cursor.fetchall()]
        for project in projects:
            for field in ('languages', 'topics', 'edited_fields'):
                try:
                    project[field] = json.loads(project.get(field) or '[]')
                except (TypeError, ValueError):
                    project[field] = []
        return projects
    except psycopg2.Error as e:
        print(f"Error getting projects: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


def get_skills_from_table():
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT category, name FROM skills ORDER BY category, id")
        rows = cursor.fetchall()
        skills_dict = {}
        for row in rows:
            cat = row['category']
            if cat not in skills_dict:
                skills_dict[cat] = []
            skills_dict[cat].append(row['name'])
        return skills_dict
    except psycopg2.Error as e:
        print(f"Error getting skills: {e}")
        return {}
    finally:
        cursor.close()
        conn.close()


def _skill_values(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def build_auto_skills(projects):
    categories = {'Languages': {}, 'Topics': {}}
    for project in projects:
        for category, field in (('Languages', 'languages'), ('Topics', 'topics')):
            seen = set()
            for value in _skill_values(project.get(field)):
                name = str(value).strip()
                normalized = name.casefold()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                entry = categories[category].setdefault(normalized, {'name': name, 'project_count': 0})
                entry['project_count'] += 1

    return {
        category: sorted(entries.values(), key=lambda entry: (-entry['project_count'], entry['name'].casefold()))
        for category, entries in categories.items()
        if entries
    }


def get_auto_skills_from_projects():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return {}
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            'SELECT languages, topics FROM projects '
            'WHERE github_repo_id IS NOT NULL AND COALESCE(github_missing, FALSE)=FALSE'
        )
        return build_auto_skills(cursor.fetchall())
    except Exception:
        logger.exception('Could not load automatically generated skills')
        return {}
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def _cv_data():
    content = get_content_from_db()
    return {
        'name': content.get('hero', {}).get('title') or 'Al-ameen Olanrewaju',
        'about': content.get('about', {}).get('content', ''),
        'manual_skills': get_skills_from_table(),
        'auto_skills': get_auto_skills_from_projects(),
        'projects': [
            {
                'title': project.get('title', ''),
                'description': project.get('description', ''),
                'technologies': (project.get('languages') or []) + (project.get('topics') or []),
            }
            for project in get_projects()
        ],
        'contact': app.config.get('RESEND_TO') or app.config.get('MAIL_USERNAME') or '',
    }


def _cv_paragraph(value):
    plain_text = str(value).encode('latin-1', 'replace').decode('latin-1')
    return escape(plain_text).replace('\n', '<br/>')


def _build_cv_pdf(data):
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(_cv_paragraph(data['name']), styles['Title']), Spacer(1, 5 * mm)]
    story.append(Paragraph('About', styles['Heading2']))
    story.append(Paragraph(_cv_paragraph(data['about'] or 'Portfolio developer.'), styles['BodyText']))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph('Skills', styles['Heading2']))
    for category, names in data['manual_skills'].items():
        story.append(Paragraph(f'<b>{_cv_paragraph(category)}</b>: {_cv_paragraph(", ".join(names))}', styles['BodyText']))
    for category, items in data['auto_skills'].items():
        labels = ', '.join(f"{item['name']} ({item['project_count']} projects)" for item in items)
        story.append(Paragraph(f'<b>{_cv_paragraph(category)}</b>: {_cv_paragraph(labels)}', styles['BodyText']))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph('Projects', styles['Heading2']))
    for project in data['projects']:
        story.append(Paragraph(f"<b>{_cv_paragraph(project['title'])}</b>", styles['BodyText']))
        if project['description']:
            story.append(Paragraph(_cv_paragraph(project['description']), styles['BodyText']))
        if project['technologies']:
            story.append(Paragraph(_cv_paragraph(', '.join(project['technologies'])), styles['BodyText']))
        story.append(Spacer(1, 2 * mm))

    story.append(Paragraph('Contact', styles['Heading2']))
    contact = data['contact'] or 'Use the contact form on the portfolio website.'
    story.append(Paragraph(_cv_paragraph(contact), styles['BodyText']))
    SimpleDocTemplate(
        output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm, title=data['name']
    ).build(story)
    return output.getvalue()


def regenerate_cv(data=None):
    global _cv_cache_hash
    data = data if data is not None else _cv_data()
    content_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    pdf = _build_cv_pdf(data)
    output_dir = os.path.dirname(CV_PDF_PATH)
    os.makedirs(output_dir, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_dir, suffix='.pdf', delete=False) as temporary_file:
            temporary_path = temporary_file.name
            temporary_file.write(pdf)
        os.replace(temporary_path, CV_PDF_PATH)
        _cv_cache_hash = content_hash
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return content_hash


def ensure_cv_is_current():
    data = _cv_data()
    content_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    if _cv_cache_hash != content_hash or not os.path.isfile(CV_PDF_PATH) or os.path.getsize(CV_PDF_PATH) == 0:
        regenerate_cv(data)
    return CV_PDF_PATH


def _send_resend_email(payload):
    api_key = app.config.get('RESEND_API_KEY')
    if not api_key:
        logger.info('Resend is not configured; skipping email')
        return False
    response = request_with_retries(
        'POST',
        'https://api.resend.com/emails',
        json=payload,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        timeout=(3.05, 10),
    )
    response.raise_for_status()
    return True


def send_resend_contact_notification(name, email, subject, message, portfolio_url):
    """Send a contact notification through Resend when configured."""
    sender = app.config.get('RESEND_FROM')
    recipient = app.config.get('RESEND_TO')
    if not sender or not recipient:
        logger.info('Resend is not configured; skipping contact notification')
        return False

    html = render_template(
        'email/contact_notification.html',
        name=name,
        email=email,
        subject=subject,
        message=message,
        portfolio_url=portfolio_url,
    )
    return _send_resend_email({
        'from': sender,
        'to': [recipient],
        'subject': f'Portfolio contact: {subject or "No Subject"}',
        'html': html,
        'reply_to': email,
    })


def send_resend_contact_reply(name, email):
    sender = app.config.get('RESEND_FROM')
    if not sender:
        logger.info('Resend sender is not configured; skipping contact auto-reply')
        return False
    html = render_template('email/contact_autoreply.html', name=name)
    return _send_resend_email({
        'from': sender,
        'to': [email],
        'subject': 'Thanks for reaching out',
        'html': html,
    })


def _whatsapp_provider():
    phone = app.config.get('CALLMEBOT_PHONE')
    api_key = app.config.get('CALLMEBOT_API_KEY')
    if not phone or not api_key:
        return None
    return CallMeBotProvider(phone, api_key)


def send_whatsapp_alert(message):
    provider = _whatsapp_provider()
    if not provider:
        logger.info('CallMeBot is not configured; skipping WhatsApp alert')
        return False
    try:
        provider.send_message(message)
        return True
    except Exception:
        logger.exception('WhatsApp alert failed')
        return False


def send_contact_alerts(name, email, subject, message, portfolio_url):
    with app.app_context():
        try:
            send_resend_contact_notification(name, email, subject, message, portfolio_url)
        except Exception:
            logger.exception('Contact notification email failed')

        try:
            send_resend_contact_reply(name, email)
        except Exception:
            logger.exception('Contact auto-reply failed')

        provider = _whatsapp_provider()
        if not provider:
            logger.info('CallMeBot is not configured; skipping WhatsApp alert')
            return
        alert = f'New portfolio message from {name} <{email}>: {message}'
        try:
            provider.send_message(alert)
        except Exception:
            logger.exception('CallMeBot contact alert failed')


# ================== REST API ==================
class ProjectListResource(Resource):
    method_decorators = {'post': [login_required]}

    def get(self):
        projects = get_projects()
        for project in projects:
            for field, value in project.items():
                if isinstance(value, datetime):
                    project[field] = value.isoformat()
        return projects, 200

    def post(self):
        data = request.get_json()
        if not data:
            return {"error": "No data provided"}, 400
        title = data.get('title')
        description = data.get('description')
        link = data.get("link", "#")
        if not title or not description:
            return {"error": "Title and description are required"}, 400
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO projects (title, description, link) VALUES (%s, %s, %s) RETURNING id",
            (title, description, link)
        )
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return {"message": "Project created!", "id": new_id}, 201


api.add_resource(ProjectListResource, '/api/v1/projects')


class ProjectResource(Resource):
    method_decorators = {'delete': [login_required]}

    def get(self, id):
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM projects WHERE id = %s", (id,))
        project = cursor.fetchone()
        cursor.close()
        conn.close()
        if not project:
            return {"error": "Project not found"}, 404
        if 'created_at' in project and project['created_at']:
            project['created_at'] = str(project['created_at'])
        return dict(project), 200

    def delete(self, id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        return {"message": "Project deleted"}, 200


api.add_resource(ProjectResource, '/api/v1/projects/<int:id>')


# ================== AUTH ==================
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/register", methods=["GET", "POST"])
def register():
    abort(404)


# ================== MAIN ROUTES ==================
@app.route('/')
@cache.cached(timeout=300)
def home():
    try:
        projects = get_projects()
        content = get_content_from_db()
        skills = get_skills_from_table()
        auto_skills = get_auto_skills_from_projects()
        services = get_service_entries(content)
        return render_template("home.html", projects=projects, content=content, skills=skills,
                       auto_skills=auto_skills, services=services)
    except Exception as e:
        print(f"Error in home route: {e}")
        return f"An error occurred: {e}", 500


@app.route('/cv.pdf', methods=['GET'])
@limiter.limit('30 per hour')
def download_cv():
    path = ensure_cv_is_current()
    with open(path, 'rb') as cv_file:
        pdf = io.BytesIO(cv_file.read())
    return send_file(pdf, mimetype='application/pdf', as_attachment=True, download_name='Al-ameen_cv.pdf')


@app.route('/project-screenshots/<int:project_id>.webp', methods=['GET'])
def project_screenshot(project_id):
    conn = get_db_connection()
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT image_data FROM project_screenshots WHERE project_id=%s', (project_id,))
        row = cursor.fetchone()
        if not row:
            abort(404)
        image_data = bytes(row[0])
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return send_file(io.BytesIO(image_data), mimetype='image/webp', max_age=3600)


@app.route("/api/projects", methods=['GET'])
def api_projects():
    return jsonify(get_projects()), 200


@app.route("/api/projects/<int:id>", methods=['GET'])
def api_project(id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM projects WHERE id = %s", (id,))
    project = cursor.fetchone()
    cursor.close()
    conn.close()
    if not project:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(dict(project)), 200


@app.route("/api/skills", methods=['GET'])
def api_skills():
    return jsonify(get_skills_from_table())


@app.route("/api", methods=['GET'])
def api_index():
    return jsonify({
        "message": "Al-ameen's portfolio API",
        "version": "1.0",
        "endpoints": ["/api/projects", "/api/projects/<id>", "/api/skills"]
    })


@app.route('/contact', methods=['POST'])
@limiter.limit("3 per minute")
def contact():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    subject = request.form.get('subject', 'No Subject').strip()
    message = request.form.get('message', '').strip()

    if not name or not email or not message:
        flash('Please fill in all required fields', 'danger')
        return redirect(url_for('home') + '#contact')

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            raise psycopg2.OperationalError('Database connection unavailable')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO contact_messages (name, email, subject, message) VALUES (%s, %s, %s, %s)",
            (name, email, subject, message)
        )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        logger.exception('Contact message could not be saved')
        flash('Your message could not be saved. Please try again.', 'danger')
        return redirect(url_for('home') + '#contact')
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    contact_alert_executor.submit(
        send_contact_alerts, name, email, subject, message, request.url_root.rstrip('/')
    )

    flash("Message sent successfully! We'll get back to you soon.", "success")
    return redirect(url_for('home', success=1) + '#contact')


# ================== ADMIN ROUTES ==================
@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def admin_login_alias():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Invalid username or password', 'danger')
            return redirect(url_for('admin_login_alias'))

        ensure_default_admin_user()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin'))

        flash('Invalid username or password', 'danger')
        return redirect(url_for('admin_login_alias'))

    return render_template('admin_login.html')


@app.route('/admin')
@login_required
def admin():
    ensure_db_schema()
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return render_template('admin.html', projects=[], messages=[], content={}, skills={})
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM projects ORDER BY is_pinned DESC, sort_order, CASE WHEN last_pushed_at IS NULL THEN 1 ELSE 0 END, last_pushed_at DESC, created_at DESC")
        projects = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM site_content")
        content_data = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM contact_messages ORDER BY created_at DESC")
        messages = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT category, name FROM skills ORDER BY category, id")
        skill_rows = [dict(r) for r in cursor.fetchall()]
        content = {}
        for row in content_data:
            content[row['section_name']] = {
                "id": row['id'],
                "section_name": row['section_name'],
                "title": row['title'] or '',
                "content": row['content'] or '',
                "file": row['file'] or ''
            }
        skills = {}
        for row in skill_rows:
            cat = row['category']
            if cat not in skills:
                skills[cat] = []
            skills[cat].append(row['name'])
        return render_template('admin.html', projects=projects, messages=messages, content=content, skills=skills)
    except psycopg2.Error as e:
        print(f"Database error in admin: {e}")
        flash(f'Database error: {e}', 'danger')
        return render_template('admin.html', projects=[], messages=[], content={}, skills={})
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/jobs', methods=['GET'])
@login_required
def admin_jobs():
    try:
        jobs = job_scheduler.statuses()
    except Exception:
        logger.exception('Could not load scheduled job status')
        flash('Scheduled job status is temporarily unavailable.', 'danger')
        jobs = []
    return render_template('admin_jobs.html', jobs=jobs)


@app.route('/admin/jobs/<job_name>/run', methods=['POST'])
@login_required
def run_scheduled_job(job_name):
    if job_name not in job_scheduler.jobs:
        abort(404)
    succeeded = job_scheduler.run_job(job_name)
    flash(
        f'{job_name} completed.' if succeeded else f'{job_name} failed or is already running.',
        'success' if succeeded else 'danger',
    )
    return redirect(url_for('admin_jobs'))


@app.route('/add_project', methods=['GET', 'POST'])
@login_required
def add_project():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        link = request.form.get('link', '').strip()
        if not title or not description:
            flash('Title and description are required!', 'danger')
            return redirect(url_for('add_project'))
        conn = get_db_connection()
        if not conn:
            flash('Database connection error', 'danger')
            return redirect(url_for('admin'))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO projects (title, description, link) VALUES (%s, %s, %s)",
                (title, description, link)
            )
            conn.commit()
            cache.clear()
            flash('Project added successfully!', 'success')
        except psycopg2.Error as e:
            flash(f'Error adding project: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for('admin'))
    return render_template('add_project.html')


@app.route('/edit_project/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_project(id):
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))
    try:
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            link = request.form.get('link', '').strip()
            cursor = conn.cursor()
            cursor.execute("SELECT title, description, link, homepage_url, github_full_name, edited_fields FROM projects WHERE id=%s", (id,))
            row = cursor.fetchone()
            if not row:
                flash('Project not found!', 'danger')
                return redirect(url_for('admin'))
            if not isinstance(row, dict):
                row = dict(zip(('title', 'description', 'link', 'homepage_url', 'github_full_name', 'edited_fields'), row))
            edited_fields = row.get('edited_fields')
            try:
                edited_fields = json.loads(edited_fields or '[]')
            except (TypeError, ValueError):
                edited_fields = []
            edited_fields = set(edited_fields)
            if title != row.get('title'):
                edited_fields.add('title')
            if description != row.get('description'):
                edited_fields.add('description')
            previous_live_link = row.get('homepage_url') if row.get('github_full_name') else row.get('link')
            if link != (previous_live_link or ''):
                edited_fields.add('link')

            cursor.execute(
                "UPDATE projects SET title=%s, description=%s, link=%s, homepage_url=%s, edited_fields=%s WHERE id=%s",
                (title, description, link if 'link' in edited_fields else row.get('link'),
                 link or None if row.get('github_full_name') else row.get('homepage_url'),
                 json.dumps(sorted(edited_fields)), id)
            )
            conn.commit()
            cache.clear()
            flash('Project updated successfully!', 'success')
            return redirect(url_for('admin'))
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM projects WHERE id=%s", (id,))
        project = cursor.fetchone()
        if not project:
            flash('Project not found!', 'danger')
            return redirect(url_for('admin'))
        return render_template('edit_project.html', project=dict(project))
    except psycopg2.Error as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('admin'))
    finally:
        cursor.close()
        conn.close()


@app.route('/delete_project/<int:id>', methods=['POST'])
@login_required
def delete_project(id):
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id=%s", (id,))
        conn.commit()
        cache.clear()
        flash('Project deleted successfully!', 'warning')
    except psycopg2.Error as e:
        flash(f'Error deleting project: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('admin'))


def _github_client():
    return GitHubClient(
        app.config.get('GITHUB_USERNAME'),
        app.config.get('GITHUB_TOKEN'),
        cache=github_api_cache,
    )


def _project_title(repo_name):
    return re.sub(r'[-_]+', ' ', repo_name).strip().title()


def sync_github_projects(repositories=None, mark_missing=True, import_new=False):
    repositories = repositories if repositories is not None else _github_client().list_repositories()
    conn = get_db_connection()
    if not conn:
        raise GitHubAPIError('Database connection error. GitHub projects were not changed.')

    imported = 0
    updated = 0
    present_ids = [repo['id'] for repo in repositories]
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, github_repo_id, edited_fields, image FROM projects WHERE github_repo_id IS NOT NULL')
        existing = {row['github_repo_id']: row for row in cursor.fetchall()}
        for repo in repositories:
            repo_id = repo['id']
            language_names = list(repo.get('languages', {}).keys())
            topics = repo.get('topics', [])
            description = (repo.get('description') or '').strip()
            homepage = (repo.get('homepage') or '').strip()
            link = homepage or repo['html_url']
            pushed_at = datetime.fromisoformat(repo['pushed_at'].replace('Z', '+00:00')) if repo.get('pushed_at') else None
            values = {
                'title': _project_title(repo['name']),
                'description': description,
                'link': link,
                'homepage_url': homepage or None,
                'image': repo.get('preview_image') or f"https://opengraph.githubassets.com/{repo_id}/{repo['full_name']}",
                'languages': json.dumps(language_names),
                'topics': json.dumps(topics),
                'stars': repo.get('stargazers_count', 0),
                'last_pushed_at': pushed_at,
                'github_full_name': repo['full_name'],
                'github_missing': False,
                'github_archived': bool(repo.get('archived')),
            }
            row = existing.get(repo_id)
            if row is None:
                if not import_new:
                    continue
                cursor.execute(
                    "INSERT INTO projects (title, description, link, homepage_url, image, github_repo_id, github_full_name, languages, topics, stars, last_pushed_at, is_visible, is_pinned, sort_order, github_missing, github_archived) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, FALSE, 0, FALSE, %s)",
                    (values['title'], values['description'], values['link'], values['homepage_url'], values['image'], repo_id,
                     values['github_full_name'], values['languages'], values['topics'], values['stars'],
                     values['last_pushed_at'], values['github_archived'])
                )
                imported += 1
                continue

            edited = row.get('edited_fields') or '[]'
            if isinstance(edited, str):
                try:
                    edited = json.loads(edited)
                except ValueError:
                    edited = []
            updates = {key: value for key, value in values.items() if key not in edited}
            if (row.get('image') or '').startswith('/project-screenshots/'):
                updates.pop('image', None)
            updates['stars'] = values['stars']
            updates['last_pushed_at'] = values['last_pushed_at']
            updates['github_full_name'] = values['github_full_name']
            updates['github_missing'] = False
            updates['github_archived'] = values['github_archived']
            assignments = ', '.join(f'{column}=%s' for column in updates)
            cursor.execute(
                f'UPDATE projects SET {assignments} WHERE id=%s',
                (*updates.values(), row['id'])
            )
            updated += 1

        if mark_missing:
            if present_ids:
                placeholders = ','.join(['%s'] * len(present_ids))
                cursor.execute(
                    f'UPDATE projects SET github_missing=TRUE WHERE github_repo_id IS NOT NULL AND github_repo_id NOT IN ({placeholders})',
                    tuple(present_ids)
                )
            else:
                cursor.execute('UPDATE projects SET github_missing=TRUE WHERE github_repo_id IS NOT NULL')
        conn.commit()
        cache.clear()
        return imported, updated
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/github/import', methods=['GET', 'POST'])
@login_required
def github_import():
    try:
        repositories = _github_client().list_repositories(enrich=False)
    except GitHubAPIError as error:
        flash(str(error), 'danger')
        return render_template('github_import.html', repositories=[])

    if request.method == 'POST':
        selected_ids = {int(value) for value in request.form.getlist('repo_ids') if value.isdigit()}
        include_forks = request.form.get('include_forks') == 'on'
        include_archived = request.form.get('include_archived') == 'on'
        selected = [
            repo for repo in repositories
            if repo['id'] in selected_ids
            and (include_forks or not repo.get('fork'))
            and (include_archived or not repo.get('archived'))
        ]
        try:
            selected = _github_client().enrich_repositories(selected)
            imported, _ = sync_github_projects(selected, mark_missing=False, import_new=True)
            flash(f'Imported {imported} GitHub repositories.', 'success')
            cache.clear()
            return redirect(url_for('admin'))
        except (GitHubAPIError, psycopg2.Error) as error:
            flash(f'GitHub import failed: {error}', 'danger')

    conn = get_db_connection()
    imported_ids = set()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT github_repo_id FROM projects WHERE github_repo_id IS NOT NULL')
            imported_ids = {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()
            conn.close()
    return render_template('github_import.html', repositories=repositories, imported_ids=imported_ids)


@app.route('/admin/github/sync', methods=['POST'])
@login_required
def github_sync():
    try:
        imported, updated = sync_github_projects()
        flash(f'GitHub sync complete: {imported} imported, {updated} updated.', 'success')
    except (GitHubAPIError, psycopg2.Error) as error:
        flash(f'GitHub sync failed: {error}', 'danger')
    cache.clear()
    return redirect(url_for('admin'))


def mark_github_repository_missing(repo_id):
    conn = get_db_connection()
    if not conn:
        raise GitHubAPIError('Database connection error. GitHub projects were not changed.')
    try:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE projects SET github_missing=TRUE WHERE github_repo_id=%s',
            (repo_id,)
        )
        conn.commit()
        cache.clear()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def check_project_links():
    conn = get_db_connection()
    if not conn:
        raise psycopg2.OperationalError('Database connection unavailable')
    cursor = None
    new_failures = []
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            'SELECT id, title, link, homepage_url, github_full_name, '
            'demo_link_status, repo_link_status FROM projects'
        )
        projects = [dict(project) for project in cursor.fetchall()]
        checked_at = datetime.now().astimezone()
        for project in projects:
            demo_url = project.get('homepage_url') if project.get('github_full_name') else project.get('link')
            repo_url = f"https://github.com/{project['github_full_name']}" if project.get('github_full_name') else None
            demo_status = check_link(demo_url) if demo_url else None
            repo_status = check_link(repo_url) if repo_url else None
            cursor.execute(
                'UPDATE projects SET demo_link_status=%s, demo_link_checked_at=%s, '
                'repo_link_status=%s, repo_link_checked_at=%s WHERE id=%s',
                (demo_status, checked_at if demo_url else None,
                 repo_status, checked_at if repo_url else None, project['id'])
            )
            if demo_status == 'broken' and project.get('demo_link_status') != 'broken':
                new_failures.append(f"{project.get('title')}: demo {demo_url}")
            if repo_status == 'broken' and project.get('repo_link_status') != 'broken':
                new_failures.append(f"{project.get('title')}: repository {repo_url}")
        conn.commit()
        cache.clear()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        conn.close()

    if new_failures:
        details = '\n'.join(new_failures[:8])
        send_whatsapp_alert(f'Portfolio link check found broken links:\n{details}'[:1300])
    return {'checked': len(projects), 'new_failures': len(new_failures)}


SCREENSHOT_MONTHLY_LIMIT = 100


def _screenshot_api_provider():
    access_key = app.config.get('SCREENSHOTONE_ACCESS_KEY')
    return ScreenshotOneProvider(access_key) if access_key else None


def _reserve_screenshot_api_request():
    month_start = datetime.now(timezone.utc).date().replace(day=1)
    conn = get_db_connection()
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO screenshot_usage (month_start, request_count, quota_exhausted) '
            'VALUES (%s, 1, FALSE) ON CONFLICT (month_start) DO UPDATE '
            'SET request_count=screenshot_usage.request_count + 1 '
            'WHERE screenshot_usage.request_count < %s AND screenshot_usage.quota_exhausted=FALSE '
            'RETURNING request_count',
            (month_start, SCREENSHOT_MONTHLY_LIMIT),
        )
        claimed = cursor.fetchone()
        if claimed:
            conn.commit()
            return True, False
        cursor.execute(
            'UPDATE screenshot_usage SET quota_exhausted=TRUE '
            'WHERE month_start=%s AND quota_exhausted=FALSE RETURNING month_start',
            (month_start,),
        )
        newly_exhausted = bool(cursor.fetchone())
        conn.commit()
        return False, newly_exhausted
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        conn.close()


def _mark_screenshot_quota_exhausted():
    month_start = datetime.now(timezone.utc).date().replace(day=1)
    conn = get_db_connection()
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE screenshot_usage SET quota_exhausted=TRUE '
            'WHERE month_start=%s AND quota_exhausted=FALSE RETURNING month_start',
            (month_start,),
        )
        newly_exhausted = bool(cursor.fetchone())
        conn.commit()
        return newly_exhausted
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        conn.close()


def _store_project_screenshot(project_id, image_data, source):
    conn = get_db_connection()
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO project_screenshots (project_id, image_data, width, height, source, updated_at) '
            'VALUES (%s, %s, 1280, 720, %s, NOW()) ON CONFLICT (project_id) DO UPDATE SET '
            'image_data=EXCLUDED.image_data, width=EXCLUDED.width, height=EXCLUDED.height, '
            'source=EXCLUDED.source, updated_at=EXCLUDED.updated_at',
            (project_id, image_data, source),
        )
        cursor.execute(
            'UPDATE projects SET image=%s WHERE id=%s AND (edited_fields IS NULL OR edited_fields NOT LIKE %s)',
            (f'/project-screenshots/{project_id}.webp', project_id, '%"image"%'),
        )
        conn.commit()
        cache.clear()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        conn.close()


def refresh_project_screenshots():
    conn = get_db_connection()
    if not conn:
        raise psycopg2.OperationalError('Database connection unavailable')
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            'SELECT id, title, description, link, homepage_url, github_full_name, '
            'languages, topics, edited_fields FROM projects WHERE is_visible=TRUE'
        )
        projects = [dict(project) for project in cursor.fetchall()]
    finally:
        if cursor:
            cursor.close()
        conn.close()

    provider = _screenshot_api_provider()
    api_blocked = provider is None
    quota_alerted = False
    api_failures = 0
    generated = 0
    for project in projects:
        edited_fields = project.get('edited_fields') or []
        if isinstance(edited_fields, str):
            try:
                edited_fields = json.loads(edited_fields)
            except ValueError:
                edited_fields = []
        if 'image' in edited_fields:
            continue

        live_url = project.get('homepage_url') if project.get('github_full_name') else project.get('link')
        if not live_url:
            continue
        technologies = _skill_values(project.get('languages')) + _skill_values(project.get('topics'))
        image_data = None
        source = 'fallback'

        if provider and not api_blocked:
            allowed, newly_exhausted = _reserve_screenshot_api_request()
            if not allowed:
                api_blocked = True
                if newly_exhausted and not quota_alerted:
                    send_whatsapp_alert('ScreenshotOne free quota reached. Generated project cards will be used until next month.')
                    quota_alerted = True
            else:
                try:
                    image_data = normalize_webp(provider.capture(live_url))
                    source = 'screenshotone'
                except ScreenshotQuotaExceeded:
                    api_blocked = True
                    newly_exhausted = _mark_screenshot_quota_exhausted()
                    if newly_exhausted and not quota_alerted:
                        send_whatsapp_alert('ScreenshotOne free quota reached. Generated project cards will be used until next month.')
                        quota_alerted = True
                except Exception:
                    logger.exception('ScreenshotOne capture failed for project %s', project['id'])
                    api_failures += 1

        if image_data is None:
            image_data = create_fallback_card(project.get('title', ''), live_url, technologies)
        _store_project_screenshot(project['id'], image_data, source)
        generated += 1

    if api_failures:
        send_whatsapp_alert(f'ScreenshotOne failed for {api_failures} project(s); generated cards were saved instead.')
    return {'generated': generated, 'api_failures': api_failures}


@app.route('/webhooks/github', methods=['POST'])
@limiter.limit('60 per minute')
@csrf.exempt
def github_webhook():
    secret = app.config.get('GITHUB_WEBHOOK_SECRET')
    if not secret:
        return jsonify({'error': 'GitHub webhook secret is not configured.'}), 503

    payload_bytes = request.get_data(cache=True)
    signature = request.headers.get('X-Hub-Signature-256', '')
    if not verify_github_signature(payload_bytes, signature, secret):
        return jsonify({'error': 'Invalid GitHub webhook signature.'}), 401

    payload = request.get_json(silent=True) or {}
    event = request.headers.get('X-GitHub-Event', '')
    repository = payload.get('repository') or {}
    repo_id = repository.get('id')
    full_name = repository.get('full_name')
    if event not in ('push', 'repository'):
        return jsonify({'message': 'Event ignored.'}), 202
    if not repo_id or not full_name:
        return jsonify({'error': 'Webhook payload has no repository identity.'}), 400

    owner = (repository.get('owner') or {}).get('login')
    configured_username = app.config.get('GITHUB_USERNAME', '')
    if owner and configured_username and owner.casefold() != configured_username.casefold():
        return jsonify({'error': 'Repository owner does not match GITHUB_USERNAME.'}), 403

    action = payload.get('action')
    if event == 'repository' and action == 'deleted':
        try:
            mark_github_repository_missing(repo_id)
            return jsonify({'message': 'Repository marked missing.'}), 200
        except (GitHubAPIError, psycopg2.Error) as error:
            logger.exception('GitHub repository deletion webhook failed')
            return jsonify({'error': str(error)}), 503

    if event == 'repository' and action not in {
        'created', 'edited', 'archived', 'unarchived', 'renamed', 'publicized', 'privatized'
    }:
        return jsonify({'message': 'Repository event ignored.'}), 202

    try:
        repository = _github_client().enrich_repositories([repository])[0]
        imported, updated = sync_github_projects(
            [repository],
            mark_missing=False,
            import_new=(event == 'repository' and action == 'created'),
        )
        return jsonify({'message': 'Repository synced.', 'imported': imported, 'updated': updated}), 200
    except (GitHubAPIError, psycopg2.Error) as error:
        logger.exception('GitHub webhook sync failed for %s', full_name)
        return jsonify({'error': 'GitHub sync failed; retry will be safe.', 'detail': str(error)}), 503


@app.route('/admin/projects/<int:id>/refresh-description', methods=['POST'])
@login_required
def refresh_project_description(id):
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            'SELECT github_full_name, edited_fields FROM projects WHERE id=%s AND github_repo_id IS NOT NULL',
            (id,)
        )
        project = cursor.fetchone()
        if not project:
            flash('This project is not linked to a GitHub repository.', 'warning')
            return redirect(url_for('admin'))

        description = _github_client().get_repository_description(project['github_full_name'])
        if not description:
            flash('GitHub has no description or README text for this repository. The saved description was left unchanged.', 'warning')
            return redirect(url_for('admin'))

        edited_fields = project.get('edited_fields') or '[]'
        if isinstance(edited_fields, str):
            try:
                edited_fields = json.loads(edited_fields)
            except ValueError:
                edited_fields = []
        edited_fields = sorted(set(edited_fields) - {'description'})
        cursor.execute(
            'UPDATE projects SET description=%s, edited_fields=%s WHERE id=%s',
            (description, json.dumps(edited_fields), id)
        )
        conn.commit()
        cache.clear()
        flash('Description refreshed from GitHub.', 'success')
    except (GitHubAPIError, psycopg2.Error) as error:
        conn.rollback()
        flash(f'Could not refresh the GitHub description: {error}', 'danger')
    finally:
        if cursor:
            cursor.close()
        conn.close()
    return redirect(url_for('admin'))


@app.route('/admin/projects/<int:id>/settings', methods=['POST'])
@login_required
def project_settings(id):
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))
    try:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE projects SET is_visible=%s, is_pinned=%s, sort_order=%s WHERE id=%s',
            (request.form.get('is_visible') == 'on', request.form.get('is_pinned') == 'on',
             int(request.form.get('sort_order', 0)), id)
        )
        conn.commit()
        cache.clear()
    except (ValueError, psycopg2.Error) as error:
        conn.rollback()
        flash(f'Project settings were not saved: {error}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('admin'))


@app.cli.command('sync-github-projects')
def sync_github_projects_command():
    """Refresh GitHub-backed projects; suitable for a daily Render Cron Job."""
    try:
        imported, updated = sync_github_projects()
        print(f'GitHub sync complete: {imported} imported, {updated} updated.')
    except GitHubAPIError as error:
        raise SystemExit(str(error)) from error


@app.route('/admin/edit_content', methods=['GET', 'POST'])
@login_required
def edit_content():
    ensure_db_schema()
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))

    if request.method == 'POST':
        try:
            cursor = conn.cursor()

            # Hero
            hero_title = request.form.get('hero_title', '').strip()
            hero_content = request.form.get('hero_content', '').strip()
            cursor.execute("SELECT id FROM site_content WHERE section_name='hero'")
            if cursor.fetchone():
                cursor.execute("UPDATE site_content SET title=%s, content=%s WHERE section_name='hero'", (hero_title, hero_content))
            else:
                cursor.execute("INSERT INTO site_content (section_name, title, content) VALUES ('hero', %s, %s)", (hero_title, hero_content))

            # About
            about_title = request.form.get('about_title', '').strip()
            about_content = request.form.get('about_content', '').strip()
            cursor.execute("SELECT id FROM site_content WHERE section_name='about'")
            if cursor.fetchone():
                cursor.execute("UPDATE site_content SET title=%s, content=%s WHERE section_name='about'", (about_title, about_content))
            else:
                cursor.execute("INSERT INTO site_content (section_name, title, content) VALUES ('about', %s, %s)", (about_title, about_content))

            service_indexes = set()
            for field_name in request.form:
                match = re.fullmatch(r'service_(\d+)_title', field_name)
                if match:
                    service_indexes.add(int(match.group(1)))
            removed_service_indexes = {
                int(value) for value in request.form.getlist('remove_service_ids') if value.isdigit()
            }
            for service_index in removed_service_indexes:
                cursor.execute("DELETE FROM site_content WHERE section_name=%s", (f'service_{service_index}',))

            for service_index in sorted(service_indexes - removed_service_indexes):
                service_title = request.form.get(f'service_{service_index}_title', '').strip()
                service_content = request.form.get(f'service_{service_index}_content', '').strip()
                section_name = f'service_{service_index}'
                cursor.execute("SELECT id FROM site_content WHERE section_name=%s", (section_name,))
                if cursor.fetchone():
                    if service_title or service_content:
                        cursor.execute(
                            "UPDATE site_content SET title=%s, content=%s WHERE section_name=%s",
                            (service_title, service_content, section_name)
                        )
                    else:
                        cursor.execute("DELETE FROM site_content WHERE section_name=%s", (section_name,))
                elif service_title or service_content:
                    cursor.execute(
                        "INSERT INTO site_content (section_name, title, content) VALUES (%s, %s, %s)",
                        (section_name, service_title, service_content)
                    )

            # Skills — clear old ones and re-insert
            cursor.execute("DELETE FROM skills")
            index = 0
            while True:
                category = request.form.get(f'skills_category_{index}')
                names = request.form.get(f'skills_name_{index}')
                if category is None:
                    break
                if category.strip() and names.strip():
                    for name in names.split(','):
                        name = name.strip()
                        if name:
                            cursor.execute(
                                "INSERT INTO skills (category, name) VALUES (%s, %s)",
                                (category.strip(), name)
                            )
                index += 1

            # Profile Photo
            photo = request.files.get('profile_photo')
            if photo and photo.filename and allowed_file(photo.filename, 'image'):
                filename = secure_filename(photo.filename)
                photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                cursor.execute("SELECT id FROM site_content WHERE section_name='profile_photo'")
                if cursor.fetchone():
                    cursor.execute("UPDATE site_content SET file=%s WHERE section_name='profile_photo'", (filename,))
                else:
                    cursor.execute("INSERT INTO site_content (section_name, title, file) VALUES ('profile_photo', 'Profile Photo', %s)", (filename,))

            # CV
            cv = request.files.get('cv_file')
            if cv and cv.filename and allowed_file(cv.filename, 'pdf'):
                filename = secure_filename(cv.filename)
                cv.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                cursor.execute("SELECT id FROM site_content WHERE section_name='cv_file'")
                if cursor.fetchone():
                    cursor.execute("UPDATE site_content SET file=%s WHERE section_name='cv_file'", (filename,))
                else:
                    cursor.execute("INSERT INTO site_content (section_name, title, file) VALUES ('cv_file', 'CV', %s)", (filename,))

            conn.commit()
            cache.clear()
            flash('Content updated successfully!', 'success')

        except psycopg2.Error as e:
            flash(f'Error: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for('edit_content'))

    # GET
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM site_content")
        content = {}
        for row in cursor.fetchall():
            content[row['section_name']] = {
                'id': row.get('id'),
                'section_name': row.get('section_name'),
                'title': row.get('title') or '',
                'content': row.get('content') or '',
                'file': row.get('file') or ''
            }

        cursor.execute("SELECT category, name FROM skills ORDER BY category, id")
        rows = cursor.fetchall()
        skills = {}
        for row in rows:
            cat = row['category']
            if cat not in skills:
                skills[cat] = []
            skills[cat].append(row['name'])

        services = get_service_entries(content)
        next_service_index = max((service['index'] for service in services), default=0) + 1
        return render_template(
            'edit_content.html', content=content or {}, skills=skills or {},
            services=services, next_service_index=next_service_index
        )
    except psycopg2.Error as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('admin'))
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/delete_message/<int:id>', methods=['POST'])
@login_required
def delete_message(id):
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM contact_messages WHERE id=%s", (id,))
        conn.commit()
        flash('Message deleted successfully!', 'success')
    except psycopg2.Error as e:
        flash(f'Error: {e}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('admin'))


def _scheduled_github_sync():
    result = sync_github_projects()
    cache.clear()
    return result


def _scheduler_failure_alert(job_name, error):
    provider = _whatsapp_provider()
    if provider:
        provider.send_message(f'Portfolio job {job_name} failed: {str(error)[:500]}')


job_scheduler = PostgresJobScheduler(
    get_db_connection,
    {
        'daily-github-sync': {'func': _scheduled_github_sync, 'interval': timedelta(days=1)},
        'daily-cv-regeneration': {'func': regenerate_cv, 'interval': timedelta(days=1)},
        'weekly-link-check': {'func': check_project_links, 'interval': timedelta(days=7)},
        'weekly-screenshot-refresh': {'func': refresh_project_screenshots, 'interval': timedelta(days=7)},
    },
    on_failure=_scheduler_failure_alert,
)


@app.before_request
def start_background_scheduler():
    if production and not app.testing and DATABASE_URL.startswith(('postgres://', 'postgresql://')):
        job_scheduler.start_if_needed()


atexit.register(job_scheduler.stop)


if __name__ == '__main__':
    app.run(debug=True)