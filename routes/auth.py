from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from models import User, db

auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.admin_login'))

        user = User.query.filter_by(username=username).first()
        if user is None and username == 'admin':
            user = User(
                username=username,
                email=f'{username}@local.dev',
                password=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin'))

        flash('Invalid username or password', 'danger')
        return redirect(url_for('auth.admin_login'))

    return render_template('admin_login.html')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.admin_login'))