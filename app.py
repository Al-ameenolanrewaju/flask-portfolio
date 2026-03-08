from flask import Flask, render_template, request, url_for, redirect, flash, session
import mysql.connector
from mysql.connector import Error
import os
from werkzeug.utils import secure_filename
from functools import wraps
import time
from flask_mail import Mail, Message
from datetime import datetime
from flask import render_template_string




app = Flask(__name__)
# Email configuration - Add this after your app config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False  # Important: Use TLS, not SSL
app.config['MAIL_USERNAME'] = 'oadedamola07@gmail.com'  # Your full Gmail address
app.config['MAIL_PASSWORD'] = 'vjex yhvb rdxw mmbt'  # App password, NOT your regular password
app.config['MAIL_DEFAULT_SENDER'] = 'oadedamola07@gmail.com'
app.secret_key = 'your-secret-key-here'

mail = Mail(app)
#with app.app_context():
   # try:
       # msg = Message(
        #    subject="Test Email from Flask",
        #    recipients=['oadedamola07@gmail.com'],
        #    body="If you receive this, Flask-Mail is working correctly!"
      #  )
      #  mail.send(msg)
     #   print("✓ Email sent successfully!")
   # except Exception as e:
      #  print(f"✗ Error: {e}")

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'StrongPassword123'  # change this!

# Database configuration
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "Adedamola0106",
    "database": "portfolio"
}


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


def allowed_file(filename, file_type='image'):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
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

@app.route('/')
def home():
    try:
        projects = get_projects()
        content = get_content_from_db()
        skills = get_skills_from_table()  # Use skills table instead of site_content

        print("Projects loaded:", len(projects))
        print("Content sections:", list(content.keys()))
        print("Skills loaded:", skills)

        return render_template("home.html",
                               projects=projects,
                               content=content,
                               skills=skills)
    except Exception as e:
        print(f"Error in home route: {e}")
        return f"An error occurred: {e}", 500





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
        print("Beautiful email sent successfully!")
        flash("Message sent successfully! We'll get back to you soon.", "success")

    except Exception as e:
        print(f"Email error: {e}")
        flash("Message saved but email notification failed.", "warning")

    return redirect(url_for('home', success=1) + '#contact')


# ================== ADMIN ROUTES ==================

@app.route('/admin')
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
def delete_project(id):
    connection = get_db_connection()
    if not connection:
        flash('Database connection error', 'danger')
        return redirect(url_for('admin'))

    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM projects WHERE id=%s", (id,))
        connection.commit()
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
@admin_required
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
                if file and file.filename and allowed_file(file.filename):
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
@admin_required
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
@admin_required
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
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Logged in successfully!', 'success')
            return redirect(url_for('admin'))
        else:
            flash('Invalid credentials', 'danger')

    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('home'))


# ================== ERROR HANDLERS ==================

#@app.errorhandler(404)
#def page_not_found(e):
    return render_template('404.html'), 404


#@app.errorhandler(500)
#def internal_server_error(e):
    return render_template('500.html'), 500


if __name__ == "__main__":
    app.run(debug=True)