from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    verified = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<User {self.username}>"

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    tasks = db.relationship('Task', backref='category', lazy='True')
    def __repr__(self):
        return f"<Category {self.name}>"

class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), unique=True, nullable=False)
    done = db.Column(db.Boolean, nullable=False, default=False)
    priority = db.Column(db.string(20), nullable=False, default="medium")
    due_date = db.Column(db.Date, nullable=True)
    category = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    def __repr__(self):
        return f"<Task {self.title}>"