from flask import Blueprint, render_template

main = Blueprint('main', __name__)
@main.route('/test-blueprint')
def test_blueprint():
    return "Blue print is Working"