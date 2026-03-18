# Al-ameen Olanrewaju — Flask Portfolio

A full-stack portfolio website built with Python Flask, MySQL and Bootstrap.

## 🌍 Live Demo
[View Live Portfolio](https://web-production-1d98b.up.railway.app)

## 🛠️ Technologies Used
- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-RESTful
- **Database:** MySQL, Flask-Migrate
- **Frontend:** HTML, CSS, Bootstrap 5, Jinja2
- **Email:** Flask-Mail
- **Caching:** Flask-Caching
- **Security:** Flask-WTF (CSRF), Flask-Limiter
- **Testing:** pytest
- **Deployment:** Railway, Gunicorn, GitHub

## ✨ Features
- Personal portfolio with projects and skills showcase
- Admin panel for content management
- REST API for projects and skills
- Contact form with email notifications
- User authentication with hashed passwords
- File upload system
- Automated testing with pytest
- Rate limiting and CSRF protection
- Cloud deployment on Railway

## 🚀 Running Locally

### Prerequisites
- Python 3.x
- MySQL

### Installation

1. Clone the repository:
\```bash
git clone https://github.com/Al-ameenolanrewaju/Flask-portfolio.git
cd Flask-portfolio
\```

2. Create virtual environment:
\```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux
\```

3. Install packages:
\```bash
pip install -r requirements.txt
\```

4. Create `.env` file:
\```
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=mysql+pymysql://root:password@localhost/portfolio
MAIL_USERNAME=your-email
MAIL_PASSWORD=your-app-password
\```

5. Run migrations:
\```bash
flask db upgrade
\```

6. Run the app:
\```bash
python app.py
\```

## 📡 API Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/v1/projects | Get all projects |
| POST | /api/v1/projects | Create new project |
| GET | /api/v1/projects/<id> | Get single project |
| DELETE | /api/v1/projects/<id> | Delete project |
| GET | /api/skills | Get all skills |

## 🔒 Security Features
- CSRF protection on all forms
- Rate limiting (5 login attempts/minute)
- Password hashing with Werkzeug
- Environment variables for secrets
- SQL injection prevention via SQLAlchemy

## 📞 Contact
- **Email:** oadedamola07@gmail.com
- **Location:** Lagos, Nigeria 🇳🇬
- **Portfolio:** [Live Site](https://web-production-1d98b.up.railway.app)

## 📄 License
MIT License — feel free to use this as a template!

---
Built with ❤️ by Al-ameen Olanrewaju | The Future Is African 🇳🇬