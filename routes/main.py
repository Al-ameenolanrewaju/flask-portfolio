from flask import Blueprint

from routes.job_finder import job_finder

main = Blueprint('main', __name__)
main.register_blueprint(job_finder)


@main.route('/test-blueprint')
def test_blueprint():
    return "Blue print is Working"