# Al-ameen Olanrewaju — Flask Portfolio

A full-stack portfolio website built with Python Flask, PostgreSQL and Bootstrap.

## 🌍 Live Demo
[View Live Portfolio](https://your-render-service.onrender.com)

## 🛠️ Technologies Used
- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-RESTful
- **Database:** PostgreSQL, Flask-Migrate
- **Frontend:** HTML, CSS, Bootstrap 5, Jinja2
- **Email:** Resend Python SDK for contact notifications; Flask-Mail remains available for legacy SMTP settings
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
- Signed GitHub webhook sync and generated language/topic skill counts
- Cached PDF CV, project screenshots and Open Graph previews
- Weekly link health checks and admin job controls
- Groq project drafts that remain private until approved
- Cloud deployment on Render

## 🚀 Running Locally

### Prerequisites
- Python 3.x
- PostgreSQL

### Installation

1. Clone the repository:
```bash
git clone https://github.com/Al-ameenolanrewaju/Flask-portfolio.git
cd Flask-portfolio
```

2. Create virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux
```

3. Install packages:
```bash
pip install -r requirements.txt
```

4. Create a local `.env` file (on Render, set these in the service dashboard):
```dotenv
SECRET_KEY=your-secret-key
DEBUG=True
# Render only; set this in the Render dashboard, not for local development.
# RENDER=true
DATABASE_URL=postgresql://username:password@localhost:5432/portfolio
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-admin-password
GITHUB_USERNAME=your-github-username
GITHUB_TOKEN=github_pat_your-token
GITHUB_WEBHOOK_SECRET=your-webhook-secret
RESEND_API_KEY=re_your_api_key
RESEND_FROM=onboarding@resend.dev
CONTACT_EMAIL=your-email@example.com
CALLMEBOT_PHONE=234XXXXXXXXXX
CALLMEBOT_API_KEY=your-callmebot-api-key
SCREENSHOTONE_ACCESS_KEY=your-screenshotone-access-key
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_DAILY_REQUEST_CAP=10
GROQ_REPLY_RESERVED_REQUESTS=2
INBOX_IMAP_HOST=imap.example.com
INBOX_IMAP_PORT=993
INBOX_USER=your-dedicated-inbox@example.com
INBOX_PASSWORD=your-mailbox-app-password
INBOX_BODY_RETENTION_DAYS=30
```

5. Apply database migrations before using the new schema:
```bash
flask --app app db upgrade
```

6. Run the app locally:
```bash
python app.py
```

Render start command: `gunicorn app:app`. Scheduled jobs run inside the web service under a PostgreSQL advisory lock; job status and a CSRF-protected **Run now** action are available in the admin panel. If a Render instance sleeps, overdue jobs run when the service wakes. No Cron Job or browser runtime is required.

Screenshot previews use ScreenshotOne's **100 free screenshots per month**. A local database counter stops requests at that limit; screenshots that cannot be captured, or projects after the limit, get generated WebP cards instead. No paid fallback is enabled. Groq generation also stops at `GROQ_DAILY_REQUEST_CAP`.

## Environment Variables
Set production values in the Render dashboard. Keep secrets out of Git.

| Variable | Where to get it | If missing |
|---|---|---|
| `DATABASE_URL` | Render PostgreSQL connection details | Database-backed features and scheduled jobs are unavailable. |
| `SECRET_KEY` | Generate a long random secret; set in Render | Production startup fails. Local development uses a non-production fallback. |
| `RENDER` | Set to `true` in the Render service environment | App uses development settings, including non-secure session cookies. |
| `ADMIN_USERNAME` | Choose in Render; defaults to `admin` | Uses the default username. |
| `ADMIN_PASSWORD` | Choose a strong password in Render | No configured admin account is created. |
| `DEBUG` | Local `.env` only; defaults to `False` | Debug mode stays off. |
| `GITHUB_USERNAME` | Your GitHub account name | Automatic and manual GitHub sync cannot run; saved projects remain available. |
| `GITHUB_TOKEN` | GitHub personal access token; optional | Unauthenticated GitHub API limit applies (typically 60 requests/hour). |
| `GITHUB_WEBHOOK_SECRET` | Create a secret and set the same value in the GitHub webhook | Webhook returns `503`; daily sync remains the fallback. |
| `RESEND_API_KEY` | Resend dashboard | Contact email cannot be delivered. |
| `RESEND_FROM` | Resend-verified sender; defaults to `onboarding@resend.dev` for testing | Uses Resend's testing sender. Replace it with your verified domain sender when ready. |
| `CONTACT_EMAIL` | Your inbox | Contact email cannot be delivered. |
| `MAIL_USERNAME` | Optional legacy SMTP account; also a fallback sender/recipient | No email fallback or CV contact address is available. |
| `MAIL_PASSWORD` | Optional legacy SMTP app password | No effect on the current Resend delivery path. |
| `MAIL_DEFAULT_SENDER` | Optional legacy SMTP setting | No effect on Resend contact delivery. |
| `CALLMEBOT_PHONE` | CallMeBot WhatsApp setup; include country code | WhatsApp alerts are skipped. |
| `CALLMEBOT_API_KEY` | CallMeBot activation message | WhatsApp alerts are skipped. |
| `SCREENSHOTONE_ACCESS_KEY` | ScreenshotOne dashboard; free tier is 100 screenshots/month | Generated WebP project cards are used. |
| `GROQ_API_KEY` | Groq console | AI summary generation is skipped; existing approved drafts remain live. |
| `GROQ_MODEL` | Choose an available Groq model; defaults to `llama-3.3-70b-versatile` | The default model is used. |
| `GROQ_DAILY_REQUEST_CAP` | Set an integer in Render; defaults to `10` | Daily cap defaults to 10 requests. |
| `GROQ_REPLY_RESERVED_REQUESTS` | Optional integer in Render; defaults to `2` | When IMAP is configured, two daily Groq requests remain available for reply classification before lower-priority generation uses the full cap. |
| `INBOX_IMAP_HOST` | Your mailbox provider's IMAP server hostname | Reply tracking is skipped until IMAP is configured. |
| `INBOX_IMAP_PORT` | Your provider's SSL IMAP port; defaults to `993` | Secure IMAP uses port 993. |
| `INBOX_USER` | Dedicated mailbox address | Reply tracking is skipped until a mailbox is configured; application replies use this address when available. |
| `INBOX_PASSWORD` | Create an app password in your mailbox provider's security settings | Reply tracking is skipped; a mailbox app password is required. |
| `INBOX_BODY_RETENTION_DAYS` | Optional integer; defaults to `30` | Message bodies are never stored; short excerpts are deleted after 30 days. |

## Local Checks
Run `make check`, or run `scripts/check.ps1` from PowerShell on Windows. In Git Bash, enable the optional pre-push hook with `git config core.hooksPath .githooks`.

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