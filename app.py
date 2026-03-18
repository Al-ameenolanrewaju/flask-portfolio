from flask import Flask, render_template, request, url_for, redirect, flash, session, jsonify
import mysql.connector
from mysql.connector import Error
import os
from werkzeug.utils import secure_filename
from functools import wraps
import time
from flask_mail import Mail, Message
from datetime import datetime
from flask import render_template_string
from config import DevelopmentConfig
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from flask_restful import Api, Resource
import logging
from flask_caching import Cache
import pymysql
pymysql.install_as_MySQLdb()
import urllib.parse
database_url = os.environ.get("DATABASE_URL", "")
if database_url and "localhost" not in database_url:
    parsed = urllib.parse.urlparse(
        database_url.replace("mysql+pymysql://", "mysql://")
    )
    db_config = {
        "host": parsed.hostname,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path[1:],
        "port": parsed.port or 3306
    }

app = Flask(__name__)
app.config.from_object(DevelopmentConfig)

mail = Mail(app)

# Load from config instead of hardcoding
ADMIN_USERNAME = app.config['ADMIN_USERNAME']
ADMIN_PASSWORD = app.config['ADMIN_PASSWORD']

# Database configuration — now pulls from .env
db_config = {
    "host": app.config['DB_HOST'],
    "user": app.config['DB_USER'],
    "password": app.config['DB_PASSWORD'],
    "database": app.config['DB_NAME']
}
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = "admin_login"

api = Api(app)
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})


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

        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO projects (title, description, link) VALUES (%s, %s, %s)",(title, description, link)

        )
        connection.commit()
        new_id = cursor.lastrowid
        connection.close()
        return {"message": "projects created!", "id": new_id}, 201

api.add_resource(ProjectListResource, '/api/v1/projects')

class ProjectResource(Resource):
    def get(self,id):
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM projects WHERE id = %s", (id,))
        project = cursor.fetchone()
        connection.close()

        if not project:
            return {"error": "Project not found"}, 404
        if 'created_at' in project and project['created_at']:
            project['created_at'] = str(project['created_at'])
        return project,200
    def delete(self,id):
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM projects WHERE id = %s", (id,))
        connection.commit()
        connection.close()
        return {"message": "Project deleted"}, 200
api.add_resource(ProjectResource, '/api/v1/projects/<int:id>')


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return f"<User {self.username}>"


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    tasks = db.relationship("Task", backref="category", lazy=True)

    def _repr_(self):
        return f"<Category {self.name}>"
class Task(db.Model):
    __tablename__ = 'tasks'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    done = db.Column(db.Boolean, default=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    priority = db.Column(db.String(20), default="medium")
    due_date = db.Column(db.Date, nullable=True)

    def __repr__(self):
        return f"<Task {self.title}>"

def get_db_connection():
    """Get database connection with retry logic"""
    max_retries = 3
    retry_delay = 1

    for attempt in range(max_retries):
        try:
            connection = mysql.connector.connect(**db_config)
            return connection
        except Error as e:
            if attempt == max_retries - 1:
                print(f"Failed to connect to database after {max_retries} attempts: {e}")
                raise
            print(f"Database connection attempt {attempt + 1} failed. Retrying...")
            time.sleep(retry_delay)

    return None


# Upload configuration
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

from routes.main import main
app.register_blueprint(main)
from routes.auth import auth
app.register_blueprint(auth, url_prefix='/auth')

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


# ================== DATABASE HELPER FUNCTIONS ==================

def get_content_from_db():
    """Get site content using dictionary cursor"""
    connection = get_db_connection()
    if not connection:
        return {}

    try:
        cursor = connection.cursor(dictionary=True)
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
    except Error as e:
        print(f"Error getting content: {e}")
        return {}
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def get_projects():
    """Get all projects"""
    connection = get_db_connection()
    if not connection:
        return []

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
        projects = cursor.fetchall()
        return projects
    except Error as e:
        print(f"Error getting projects: {e}")
        return []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


def get_skills_from_table():
    """Get skills from skills table"""
    connection = get_db_connection()
    if not connection:
        return {}

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT category, name FROM skills ORDER BY category, id")
        rows = cursor.fetchall()

        skills_dict = {}
        for row in rows:
            cat = row['category']
            if cat not in skills_dict:
                skills_dict[cat] = []
            skills_dict[cat].append(row['name'])
        return skills_dict
    except Error as e:
        print(f"Error getting skills: {e}")
        return {}
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


# ================== ADMIN REQUIRED DECORATOR ==================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('You need to login first!', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)

    return decorated_function


# ================== MAIN ROUTES ==================
@app.route("/cache-test")
def cache_test():
    import time
    start = time.time()
    project = get_projects()
    end = time.time()
    return jsonify({
        "project_count": len(project),
        "time_taken": f"{(end - start) * 1000:.2f}ms",
    })

@app.route('/')
@cache.cached(timeout=300)
def home():
    try:
        projects = get_projects()
        content = get_content_from_db()
        skills = get_skills_from_table()  # Use skills table instead of site_content

        return render_template("home.html",
                               projects=projects,
                               content=content,
                               skills=skills)
    except Exception as e:
        print(f"Error in home route: {e}")
        return f"An error occurred: {e}", 500

@app.route("/api/projects", methods=['GET'])
def api_projects():
    projects = get_projects()
    return jsonify(projects), 200

@app.route("/api/projects/<int:id>", methods=['GET', 'POST'])
def api_project(id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM projects WHERE id = %s", (id,))
    projects = cursor.fetchone()
    connection.close()

    if not projects:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(projects), 200

@app.route("/api/projects", methods=["POST"])
def api_create_project():
    print("POST endpoint hit!")
    data = request.get_json()
    print (f"Data received: {data}")

    if not data:
        return jsonify({"error": "No data provided"}), 400

    title = data.get("title")
    description = data.get("description")
    link = data.get("link", "#")

    if not title or not description:
        return jsonify({"error": "Title and description are required"}), 400

    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO projects (title, description, link) VALUES (%s, %s, %s)",
        (title, description, link)
    )
    connection.commit()
    new_id = cursor.lastrowid
    connection.close()

    return jsonify({
        "message": "Project created successfully!",
        "id": new_id
    }), 201

@app.route("/api/skills", methods=['GET', 'POST'])
def api_skills():
    skills = get_skills_from_table()
    return jsonify(skills)

@app.route("/api", methods=['GET', 'POST'])
def api_index():
    return jsonify({
        "message": "Al-ameen's portfolio API",
        "version": "1.0",
        "endpoints": [
            "/api/projects",
            "/api/projects/<id>",
            "/api/skills"
        ]
    })



@login_manager.user_loader
def load_user(user_id):
     return db.session.get(User, int(user_id))


@app.route("/register",methods=["GET","POST"])
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

        new_user = User(
            username=username,
            email=email,
            password=hashed_password
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully! Please login", "success")
        return redirect(url_for('admin_login'))
    return render_template("register.html")

@app.route('/contact', methods=['POST'])
def contact():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    subject = request.form.get('subject', 'No Subject').strip()
    message = request.form.get('message', '').strip()

    if not name or not email or not message:
        flash('Please fill in all required fields', 'danger')
        return redirect(url_for('home') + '#contact')

    # Save to database
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO contact_messages (name, email, subject, message) VALUES (%s, %s, %s, %s)",
                (name, email, subject, message)
            )
            connection.commit()
            cursor.close()
        except Exception as e:
            print(f"Database error: {e}")
        finally:
            connection.close()

    # Send beautiful HTML email
    try:
        # Render HTML template
        html_body = render_template(
            'email/contact_notification.html',
            name=name,
            email=email,
            subject=subject,
            message=message,
            now=datetime.now(),
            portfolio_url=url_for('home', _external=True),
            admin_url=url_for('admin', _external=True)
        )

        # Plain text version for email clients that don't support HTML
        text_body = f"""
New Contact Message from {name}

Name: {name}
Email: {email}
Subject: {subject}
Date: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

Message:
{message}

---
View in admin panel: {url_for('admin', _external=True)}
        """

        msg = Message(
            subject=f"✨ New Portfolio Message from {name}",
            recipients=['oadedamola07@gmail.com'],
            body=text_body,
            html=html_body
        )

        # You can also add reply-to
        msg.reply_to = email

        mail.send(msg)
        auto_reply = Message(
            subject=f"Thanks for reaching out, {name}",
            recipients=[email],
            html=f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #2c3e50;">Hi {name}! 👋</h2>
            <p>Thank you for reaching out! I have received your message:</p>
            <blockquote style="background: #f5f5f5; padding: 15px; border-left: 4px solid #3498db;">
                {message}
            </blockquote>
            <p>I'll get back to you within <strong>24 hours</strong>.</p>
            <hr>
            <p style="color: #888;">Best regards,<br>
            <strong>Al-ameen Olanrewaju</strong><br>
            Python Developer | Lagos, Nigeria 🇳🇬</p>
        </div>
        """,
        body=f"""
            Hi {name},
            
            Thank you for reaching out! I have received your message and will get back to you within 24 hours.
            
            Best regards,
            Al-ameen Olanrewaju
                    """

        )
        mail.send(auto_reply)
        logger.info(f'Auto-reply sent to {email}')
    except Exception as e:
        logger.info(f'Auto-reply Failed: {e}')
            
        flash("Message sent successfully! We'll get back to you soon.", "success")

    except Exception as e:
        print(f"Email error: {e}")
        flash("Message saved but email notification failed.", "warning")

    return redirect(url_for('home', success=1) + '#contact')


# ================== ADMIN ROUTES ==================

@app.route('/admin')
@login_required
def admin():
    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return render_template('admin.html', projects=[], messages=[], content={}, skills={})

    try:
        cursor = connection.cursor(dictionary=True)

        # Get projects
        cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
        projects = cursor.fetchall()

        # Get site content
        cursor.execute("SELECT * FROM site_content")
        content_data = cursor.fetchall()

        # Get contact messages
        cursor.execute("SELECT * FROM contact_messages ORDER BY created_at DESC")
        messages = cursor.fetchall()

        # Get skills
        cursor.execute("SELECT category, name FROM skills ORDER BY category, id")
        skill_rows = cursor.fetchall()

        # Build content dictionary
        content = {}
        for row in content_data:
            content[row['section_name']] = {
                "id": row['id'],
                "section_name": row['section_name'],
                "title": row['title'] or '',
                "content": row['content'] or '',
                "file": row['file'] or ''
            }

        # Build skills dictionary
        skills = {}
        for row in skill_rows:
            cat = row['category']
            if cat not in skills:
                skills[cat] = []
            skills[cat].append(row['name'])

        return render_template('admin.html',
                               projects=projects,
                               messages=messages,
                               content=content,
                               skills=skills)

    except Error as e:
        print(f"Database error in admin: {e}")
        flash(f'Database error: {e}', 'danger')
        return render_template('admin.html', projects=[], messages=[], content={}, skills={})
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


# ================== PROJECT ROUTES ==================

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

        connection = get_db_connection()
        if not connection:
            flash('Database connection error', 'danger')
            return redirect(url_for('admin'))

        try:
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO projects (title, description, link) VALUES (%s, %s, %s)",
                (title, description, link)
            )
            connection.commit()
            cache.clear()
            logger.info("Cache cleared after adding project")
            flash('Project added successfully!', 'success')
        except Error as e:
            print(f"Error adding project: {e}")
            flash(f'Error adding project: {e}', 'danger')
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

        return redirect(url_for('admin'))

    return render_template('add_project.html')


@app.route('/edit_project/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_project(id):
    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))

    try:
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            link = request.form.get('link', '').strip()

            cursor = connection.cursor()
            cursor.execute(
                "UPDATE projects SET title=%s, description=%s, link=%s WHERE id=%s",
                (title, description, link, id)
            )
            connection.commit()
            cache.clear()
            flash('Project updated successfully!', 'success')
            return redirect(url_for('admin'))

        # GET request - fetch project data
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM projects WHERE id=%s", (id,))
        project = cursor.fetchone()

        if not project:
            flash('Project not found!', 'danger')
            return redirect(url_for('admin'))

        return render_template('edit_project.html', project=project)

    except Error as e:
        print(f"Error editing project: {e}")
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('admin'))
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()


@app.route('/delete_project/<int:id>')
@login_required
def delete_project(id):
    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))

    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM projects WHERE id=%s", (id,))
        connection.commit()
        cache.clear()
        flash('Project deleted successfully!', 'warning')
    except Error as e:
        print(f"Error deleting project: {e}")
        flash(f'Error deleting project: {e}', 'danger')
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return redirect(url_for('admin'))


# ================== CONTENT EDITING ROUTES ==================

@app.route('/admin/edit_content', methods=['GET', 'POST'])
@login_required
def edit_content():
    if request.method == 'POST':
        connection = get_db_connection()
        if not connection:
            flash('Database connection error', 'danger')
            return redirect(url_for('edit_content'))

        try:
            cursor = connection.cursor()

            # Update hero section
            hero_title = request.form.get('hero_title', '')
            hero_content = request.form.get('hero_content', '')
            cursor.execute(
                "UPDATE site_content SET title=%s, content=%s WHERE section_name='hero'",
                (hero_title, hero_content)
            )

            # Update about section
            about_title = request.form.get('about_title', '')
            about_content = request.form.get('about_content', '')
            cursor.execute(
                "UPDATE site_content SET title=%s, content=%s WHERE section_name='about'",
                (about_title, about_content)
            )

            # Handle profile photo upload
            if 'profile_photo' in request.files:
             file = request.files['profile_photo']
             if file and file.filename:
                if not allowed_file(file.filename):
                    flash('Invalid file type! Only png, jpg, jpeg, gif allowed.', 'danger')
                else:
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    cursor.execute(
                        "UPDATE site_content SET file=%s WHERE section_name='profile_photo'",
                        (filename,)
                    )

            # Handle CV upload
            if 'cv_file' in request.files:
                file = request.files['cv_file']
                if file and file.filename and allowed_file(file.filename, 'pdf'):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    cursor.execute(
                        "UPDATE site_content SET file=%s WHERE section_name='cv_file'",
                        (filename,)
                    )

            connection.commit()

            # Handle skills - clear and reinsert
            cursor.execute("DELETE FROM skills")

            # Process skills from form
            index = 0
            while True:
                category = request.form.get(f"skills_category_{index}")
                name = request.form.get(f"skills_name_{index}")
                if not category or not name:
                    break
                cursor.execute(
                    "INSERT INTO skills (category, name) VALUES (%s, %s)",
                    (category.strip(), name.strip())
                )
                index += 1

            connection.commit()
            flash('Content updated successfully!', 'success')
            cache.clear()

        except Error as e:
            print(f"Error updating content: {e}")
            flash(f'Error updating content: {e}', 'danger')
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

        return redirect(url_for('edit_content'))

    # GET request - display form
    content = get_content_from_db()
    skills = get_skills_from_table()

    return render_template('edit_content.html', content=content, skills=skills)


# ================== SKILLS ROUTES ==================

@app.route('/admin/add_skill', methods=['POST'])
@login_required
def add_skill():
    category = request.form.get('category', '').strip()
    name = request.form.get('name', '').strip()

    if not category or not name:
        flash('Category and name are required!', 'danger')
        return redirect(url_for('admin'))

    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))

    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO skills (category, name) VALUES (%s, %s)",
            (category, name)
        )
        connection.commit()
        cache.clear()
        flash('Skill added successfully!', 'success')
    except Error as e:
        print(f"Error adding skill: {e}")
        flash(f'Error adding skill: {e}', 'danger')
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return redirect(url_for('admin'))


# ================== MESSAGE ROUTES ==================

@app.route('/admin/delete_message/<int:id>', methods=['POST'])
@login_required
def delete_message(id):
    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))

    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM contact_messages WHERE id=%s", (id,))
        connection.commit()
        flash('Message deleted successfully!', 'warning')
    except Error as e:
        print(f"Error deleting message: {e}")
        flash(f'Error deleting message: {e}', 'danger')
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

    return redirect(url_for('admin'))


# ================== AUTH ROUTES ==================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            logger.info(f"user {username} logged in successfully")
            flash('Logged in successfully!', 'success')
            return redirect(url_for('admin'))
        else:
            logger.warning(f"Failed login attempt for username {username}")
            flash('Invalid username or password', 'danger')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('home'))


# ================== ERROR HANDLERS ==================

#@app.errorhandler(404)
#def page_not_found(e):
    return render_template('404.html'), 404


#@app.errorhandler(500)
#def internal_server_error(e):
    return render_template('500.html'), 500

@app.errorhandler(404)
def page_not_found(e):
    logger.info(f"404 error: {request.url}")
    return render_template('404.html'), 404
@app.errorhandler(500)
def server_error(e):
    logger.critical(f"500 error: {e} - URL: {request.url}")
    return render_template('500.html'), 500

if __name__ == "__main__":
    app.run(debug=True)