from flask import Blueprint

from routes.company_briefing import company_briefing
from routes.job_finder import job_finder

main = Blueprint('main', __name__)
main.register_blueprint(job_finder)
main.register_blueprint(company_briefing)


@main.route('/test-blueprint')
def test_blueprint():
    return "Blue print is Working"