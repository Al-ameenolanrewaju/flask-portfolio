from flask import flask, Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_caching import Cache

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
cache = Cache()

def create_app(config=None):
    app = Flask(__name__)

    if config:
        app.config.from_object(config)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)

    return app
