import os

from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    DEBUG = os.environ.get("DEBUG", "False") == "True"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Database - fix "postgres://" to "postgresql://" for SQLAlchemy
    _db_url = os.environ.get("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url

    # Admin
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")

    # Email
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")
    MAIL_TIMEOUT = 5

    # Resend email delivery
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
    RESEND_FROM = os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
    CALLMEBOT_PHONE = os.environ.get("CALLMEBOT_PHONE")
    CALLMEBOT_API_KEY = os.environ.get("CALLMEBOT_API_KEY")
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_DAILY_REQUEST_CAP = os.environ.get("GROQ_DAILY_REQUEST_CAP", "10")
    GROQ_REPLY_RESERVED_REQUESTS = os.environ.get("GROQ_REPLY_RESERVED_REQUESTS", "2")
    INBOX_IMAP_HOST = os.environ.get("INBOX_IMAP_HOST")
    INBOX_IMAP_PORT = os.environ.get("INBOX_IMAP_PORT", "993")
    INBOX_USER = os.environ.get("INBOX_USER")
    INBOX_PASSWORD = os.environ.get("INBOX_PASSWORD")
    INBOX_BODY_RETENTION_DAYS = os.environ.get("INBOX_BODY_RETENTION_DAYS", "30")
    CALENDAR_TIMEZONE = os.environ.get("CALENDAR_TIMEZONE", "Africa/Lagos")
    SCREENSHOTONE_ACCESS_KEY = os.environ.get("SCREENSHOTONE_ACCESS_KEY")


class DevelopmentConfig(Config):
    DEBUG = True
    SECRET_KEY = os.environ.get("SECRET_KEY") or "local-development-key"


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_SSL_STRICT = False


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    SECRET_KEY = os.environ.get("SECRET_KEY") or "test-only-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///memory:"
    WTF_CSRF_ENABLED = False