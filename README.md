# Al-ameen Olanrewaju — Flask Portfolio

A full-stack portfolio website built with Python Flask, MySQL and Bootstrap.

## 🌍 Live Demo
[View Live Portfolio](https://your-render-service.onrender.com)

## 🛠️ Technologies Used
- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-RESTful
- **Database:** MySQL, Flask-Migrate
- **Frontend:** HTML, CSS, Bootstrap 5, Jinja2
- **Email:** Flask-Mail
- **Caching:** Flask-Caching
- **Security:** Flask-WTF (CSRF), Flask-Limiter
- **Testing:** pytest
- **Deployment:** Render, Gunicorn, GitHub

## ✨ Features
- Personal portfolio with projects and skills showcase
- Admin panel for content management
- REST API for projects and skills
- Contact form with email notifications
- User authentication with hashed passwords
- File upload system
- Automated testing with pytest
- Rate limiting and CSRF protection
- Cloud deployment on Render

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
DATABASE_URL=postgresql://username:password@localhost:5432/portfolio
GITHUB_USERNAME=your-github-username
# Optional; raises the GitHub API limit from 60 to 5,000 requests/hour
GITHUB_TOKEN=github_pat_your-token
MAIL_USERNAME=your-email
MAIL_PASSWORD=your-app-password
RESEND_API_KEY=re_your_api_key
RESEND_FROM=Portfolio <onboarding@your-verified-domain.com>
RESEND_TO=your-admin-email@example.com
\```

5. Run migrations:
\```bash
flask db upgrade
\```

6. Run the app:
\```bash
python app.py
\```

For daily GitHub synchronization, add a Render Cron Job for this project and schedule `flask --app app sync-github-projects` once per day. The admin panel also provides a manual **Sync now** action.

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
- **Portfolio:** [Live Site](https://your-render-service.onrender.com)

## 📄 License
MIT License — feel free to use this as a template!

---
Built with ❤️ by Al-ameen Olanrewaju | The Future Is African 🇳🇬