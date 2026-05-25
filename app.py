from flask import Flask, render_template, request, url_for, redirect, flash, session, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from werkzeug.utils import secure_filename
from functools import wraps
import time
from flask_mail import Mail
from flask_migrate import Migrate
from flask_login import LoginManager, login_required
from werkzeug.security import generate_password_hash
from flask_restful import Api, Resource
import logging
from flask_caching import Cache
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import DevelopmentConfig
from models import db, User, Category, Task

app = Flask(__name__)
app.config.from_object(DevelopmentConfig)

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
csrf = CSRFProtect(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# ================== BLUEPRINTS ==================
from routes.main import main
app.register_blueprint(main)
from routes.auth import auth
app.register_blueprint(auth, url_prefix='/auth')

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


def get_projects():
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
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


# ================== REST API ==================
class ProjectListResource(Resource):
    def get(self):
        projects = get_projects()
        for project in projects:
            if 'created_at' in project and project['created_at']:
                project['created_at'] = str(project['created_at'])
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
@limiter.limit("3 per minute")
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists!", "danger")
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully! Please login", "success")
        return redirect(url_for('auth.admin_login'))
    return render_template("register.html")


# ================== MAIN ROUTES ==================
@app.route('/')
@cache.cached(timeout=300)
def home():
    try:
        projects = get_projects()
        content = get_content_from_db()
        skills = get_skills_from_table()
        return render_template("home.html", projects=projects, content=content, skills=skills)
    except Exception as e:
        print(f"Error in home route: {e}")
        return f"An error occurred: {e}", 500


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
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO contact_messages (name, email, subject, message) VALUES (%s, %s, %s, %s)",
                (name, email, subject, message)
            )
            conn.commit()
            cursor.close()
            logger.info(f"Message saved from {name}")
        except Exception as e:
            logger.error(f"Database error: {e}")
        finally:
            conn.close()
    flash("Message sent successfully! We'll get back to you soon.", "success")
    return redirect(url_for('home', success=1) + '#contact')


# ================== ADMIN ROUTES ==================
@app.route('/admin')
@login_required
def admin():
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return render_template('admin.html', projects=[], messages=[], content={}, skills={})
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
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
            cursor.execute(
                "UPDATE projects SET title=%s, description=%s, link=%s WHERE id=%s",
                (title, description, link, id)
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


@app.route('/delete_project/<int:id>')
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


@app.route('/admin/edit_content', methods=['GET', 'POST'])
@login_required
def edit_content():
    conn = get_db_connection()
    if not conn:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))

    if request.method == 'POST':
        try:
            cursor = conn.cursor()
            section_name = request.form.get('section_name')
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()

            # Handle file upload
            file = request.files.get('file')
            filename = None
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            # Check if section exists
            cursor.execute("SELECT id FROM site_content WHERE section_name = %s", (section_name,))
            existing = cursor.fetchone()

            if existing:
                if filename:
                    cursor.execute(
                        "UPDATE site_content SET title=%s, content=%s, file=%s WHERE section_name=%s",
                        (title, content, filename, section_name)
                    )
                else:
                    cursor.execute(
                        "UPDATE site_content SET title=%s, content=%s WHERE section_name=%s",
                        (title, content, section_name)
                    )
            else:
                cursor.execute(
                    "INSERT INTO site_content (section_name, title, content, file) VALUES (%s, %s, %s, %s)",
                    (section_name, title, content, filename or '')
                )

            conn.commit()
            cache.clear()
            flash('Content updated successfully!', 'success')
        except psycopg2.Error as e:
            flash(f'Error updating content: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for('edit_content'))

    # GET - load all content
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM site_content")
        content_data = [dict(r) for r in cursor.fetchall()]
        content = {}
        for row in content_data:
            content[row['section_name']] = row
        return render_template('edit_content.html', content=content)
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


if __name__ == '__main__':
    app.run(debug=True)