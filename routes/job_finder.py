import logging

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from job_finder_service import DEFAULT_PREFERENCES, job_finder_service, parse_preferences


logger = logging.getLogger(__name__)
job_finder = Blueprint('job_finder', __name__, url_prefix='/admin/job-finder')


@job_finder.route('/', methods=['GET'])
@login_required
def dashboard():
    try:
        preferences = job_finder_service.get_preferences()
        jobs = job_finder_service.list_jobs(limit=100)
        source_runs = job_finder_service.recent_source_runs()
    except Exception:
        logger.exception('Job Finder dashboard could not load')
        flash('Job Finder data is unavailable. Apply pending database migrations and try again.', 'danger')
        preferences = dict(DEFAULT_PREFERENCES)
        jobs = []
        source_runs = []
    return render_template(
        'job_finder.html', preferences=preferences, jobs=jobs,
        source_runs=source_runs, source_registry=job_finder_service.sources,
    )


@job_finder.route('/preferences', methods=['POST'])
@login_required
def save_preferences():
    try:
        preferences = parse_preferences(request.form)
        job_finder_service.save_preferences(preferences)
        flash('Job Finder preferences saved.', 'success')
    except ValueError as error:
        flash(str(error), 'danger')
    except Exception:
        logger.exception('Job Finder preferences could not be saved')
        flash('Preferences could not be saved. Check the database and try again.', 'danger')
    return redirect(url_for('main.job_finder.dashboard'))


@job_finder.route('/run-now', methods=['POST'])
@login_required
def run_now():
    try:
        if not job_finder_service.allow_action(current_user.get_id(), 'run-now', 3, 3600):
            flash('Job Finder Run now is limited to three requests per hour.', 'warning')
            return redirect(url_for('main.job_finder.dashboard'))
        scheduler = current_app.extensions.get('job_scheduler')
        if scheduler is None or 'job-finder-fetch' not in scheduler.jobs:
            abort(503)
        succeeded = scheduler.run_job('job-finder-fetch')
        flash(
            'Job Finder scan finished.' if succeeded else 'Job Finder scan failed or is already running.',
            'success' if succeeded else 'danger',
        )
    except Exception:
        logger.exception('Manual Job Finder scan failed')
        flash('Job Finder could not run. Existing saved jobs are unchanged.', 'danger')
    return redirect(url_for('main.job_finder.dashboard'))
