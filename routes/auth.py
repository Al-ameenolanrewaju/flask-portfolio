from flask import Blueprint, render_template, request, redirect, url_for,flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import check_password_hash

auth = Blueprint('auth', __name__)

@auth.route('/test-auth')
def test_auth():
    return "Auth Blueprint is Working"