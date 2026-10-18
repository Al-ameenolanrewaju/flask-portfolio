import logging

from flask import Blueprint, abort, current_app, flash, render_template, request
from flask_login import login_required

from job_finder_service import job_finder_service

logger = logging.getLogger(__name__)
company_briefing = Blueprint('company_briefing', __name__, url_prefix='/admin/job-finder')


@company_briefing.route('/jobs/<int:job_id>/briefing', methods=['GET', 'POST'])
@login_required
def view(job_id):
    job = job_finder_service.get_job(job_id)
    if not job:
        abort(404)
    service = current_app.extensions.get('company_briefing_service')
    if service is None:
        abort(503)
    if request.method == 'POST':
        try:
            briefing = service.generate(job, request.form.get('company_url', ''))
        except Exception as error:  # noqa: BLE001
            logger.error('Company briefing generation failed for job %s (%s)', job_id, type(error).__name__)
            flash('Briefing could not be refreshed. Any saved briefing remains available.', 'danger')
        else:
            flash('Briefing refreshed. Verify the cited sources yourself.', 'success')
            return render_template(
                'job_finder_briefing.html', job=job, briefing=briefing,
                company_url=request.form.get('company_url', ''),
            )
    briefing = service.get(job_id)
    sources = (briefing or {}).get('sources_json') or []
    company_url = next((source['url'] for source in sources if source['url'] != job['posting_url']), '')
    return render_template(
        'job_finder_briefing.html', job=job, briefing=briefing,
        company_url=company_url,
    )