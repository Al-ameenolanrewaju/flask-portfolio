import hashlib
import json
import logging
from base64 import b64encode
from html import escape

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from job_finder_service import (
    DEFAULT_PREFERENCES,
    job_finder_service,
    parse_preferences,
)
from reply_tracking import build_job_reply_to

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


@job_finder.route('/inbox', methods=['GET'])
@login_required
def inbox():
    tracker = current_app.extensions.get('inbox_reply_tracker')
    if tracker is None:
        abort(503)
    view_all = request.args.get('view') == 'all'
    try:
        replies = tracker.list_replies(needs_review=None if view_all else True)
    except Exception:
        logger.exception('Inbox replies could not be loaded')
        flash('Inbox replies are unavailable. Apply pending database migrations and try again.', 'danger')
        replies = []
    return render_template('job_finder_inbox.html', replies=replies, view_all=view_all)


@job_finder.route('/inbox/<int:reply_id>/review', methods=['POST'])
@login_required
def review_reply(reply_id):
    tracker = current_app.extensions.get('inbox_reply_tracker')
    if tracker is None:
        abort(503)
    try:
        updated = tracker.review_reply(reply_id, request.form.get('status', ''))
    except ValueError as error:
        flash(str(error), 'danger')
    except Exception:
        logger.exception('Inbox reply review failed for %s', reply_id)
        flash('Reply review failed. No status change was saved.', 'danger')
    else:
        if not updated:
            abort(404)
        flash('Reply reviewed and the selected status saved.', 'success')
    return redirect(url_for('main.job_finder.inbox'))


@job_finder.route('/inbox/<int:reply_id>/undo', methods=['POST'])
@login_required
def undo_reply(reply_id):
    tracker = current_app.extensions.get('inbox_reply_tracker')
    if tracker is None:
        abort(503)
    try:
        undone = tracker.undo_status_change(reply_id)
    except ValueError as error:
        flash(str(error), 'warning')
    except Exception:
        logger.exception('Inbox reply status undo failed for %s', reply_id)
        flash('The status change could not be undone.', 'danger')
    else:
        if not undone:
            abort(404)
        flash('The automatic job status change was undone.', 'success')
    return redirect(url_for('main.job_finder.inbox'))


@job_finder.route('/master-profile', methods=['GET', 'POST'])
@login_required
def master_profile():
    if request.method == 'POST':
        profile = {
            'full_name': request.form.get('full_name', ''),
            'email': request.form.get('email', ''),
            'phone': request.form.get('phone', ''),
            'city_country': request.form.get('city_country', ''),
            'links': {
                'portfolio': request.form.get('portfolio_url', ''),
                'github': request.form.get('github_url', ''),
                'linkedin': request.form.get('linkedin_url', ''),
            },
            'education': request.form.get('education', ''),
            'work_history': request.form.getlist('work_history'),
            'achievements': request.form.getlist('achievements'),
            'skills': request.form.getlist('skills'),
            'languages': request.form.getlist('languages'),
            'availability': request.form.get('availability', ''),
            'start_date': request.form.get('start_date', ''),
            'notice_period': request.form.get('notice_period', ''),
            'work_authorization': request.form.get('work_authorization', ''),
            'preferred_work_mode': request.form.get('preferred_work_mode', ''),
            'salary_expectation': request.form.get('salary_expectation', ''),
            'projects': request.form.getlist('projects'),
            'summary': request.form.get('summary', ''),
        }
        job_finder_service.save_master_profile(profile)
        flash('Master profile saved.', 'success')
        return redirect(url_for('main.job_finder.master_profile'))

    profile = job_finder_service.get_master_profile()
    return render_template('job_finder_master_profile.html', profile=profile)


@job_finder.route('/jobs/<int:job_id>/pack', methods=['GET'])
@login_required
def application_pack(job_id):
    job = job_finder_service.get_job(job_id)
    if not job:
        abort(404)
    profile = job_finder_service.get_master_profile()
    pack = job_finder_service.get_application_pack(job_id)
    if not pack:
        pack = job_finder_service.build_application_pack(job, profile)
        job_finder_service.save_application_pack(
            job_id,
            pack,
            hashlib.sha256(json.dumps({
                'posting_url': job.get('posting_url'),
                'title': job.get('title'),
                'company': job.get('company'),
                'description': job.get('description'),
            }, sort_keys=True, default=str).encode('utf-8')).hexdigest(),
        )
    return render_template('job_finder_application_pack.html', job=job, profile=profile, pack=pack)


@job_finder.route('/jobs/<int:job_id>/pack/regenerate', methods=['POST'])
@login_required
def regenerate_application_pack(job_id):
    job = job_finder_service.get_job(job_id)
    if not job:
        abort(404)
    profile = job_finder_service.get_master_profile()
    pack = job_finder_service.build_application_pack(job, profile)
    job_finder_service.save_application_pack(
        job_id,
        pack,
        hashlib.sha256(json.dumps({
            'posting_url': job.get('posting_url'),
            'title': job.get('title'),
            'company': job.get('company'),
            'description': job.get('description'),
        }, sort_keys=True, default=str).encode('utf-8')).hexdigest(),
    )
    flash('Application pack regenerated.', 'success')
    return redirect(url_for('main.job_finder.application_pack', job_id=job_id))


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


@job_finder.route('/jobs/<int:job_id>/review', methods=['POST'])
@login_required
def review_job(job_id):
    action = request.form.get('action', 'save')
    follow_up_value = request.form.get('follow_up_date', '').strip()
    try:
        from datetime import date
        follow_up_date = date.fromisoformat(follow_up_value) if follow_up_value else None
        status = job_finder_service.update_review(
            job_id,
            action,
            cover_letter=request.form.get('cover_letter', ''),
            pitch_lines=request.form.getlist('pitch_line') or request.form.get('pitch', ''),
            notes=request.form.get('notes', ''),
            follow_up_date=follow_up_date,
        )
        if status is False:
            abort(404)
        flash('Job review saved.' if action == 'save' else f'Job status updated: {status}.', 'success')
    except ValueError as error:
        flash(str(error), 'danger')
    except Exception:
        logger.exception('Job Finder review could not be saved for job %s', job_id)
        flash('Job review could not be saved. The existing record is unchanged.', 'danger')
    return redirect(url_for('main.job_finder.dashboard'))


def _email_preview(job):
    subject = f"Application for {job['title']}"
    pitch = job.get('pitch') or ''
    pitch_html = ''.join(f'<li>{escape(line)}</li>' for line in pitch.splitlines() if line.strip())
    cover_html = escape(job.get('cover_letter') or '').replace('\n', '<br>')
    body = f'<p>{cover_html}</p>'
    if pitch_html:
        body += f'<p>Relevant experience:</p><ul>{pitch_html}</ul>'
    return subject, body


@job_finder.route('/jobs/<int:job_id>/send-preview', methods=['GET'])
@login_required
def send_preview(job_id):
    try:
        job = job_finder_service.get_job(job_id)
    except Exception:
        logger.exception('Job Finder send preview could not load job %s', job_id)
        flash('The approved draft is temporarily unavailable.', 'danger')
        return redirect(url_for('main.job_finder.dashboard'))
    if not job or job.get('status') != 'approved':
        abort(404)
    if not job.get('application_email'):
        flash('This source lists no application email. Open the posting and apply manually.', 'warning')
        return redirect(url_for('main.job_finder.dashboard'))

    subject, body = _email_preview(job)
    sender = current_app.config.get('RESEND_FROM') or 'onboarding@resend.dev'
    reply_to = build_job_reply_to(
        current_app.config.get('INBOX_USER') or current_app.config.get('CONTACT_EMAIL'), job['id'],
    )
    can_send = bool(current_app.config.get('RESEND_API_KEY') and reply_to and job.get('cover_letter'))
    return render_template(
        'job_finder_send_preview.html', job=job, subject=subject, body=body,
        sender=sender, reply_to=reply_to, can_send=can_send,
    )


@job_finder.route('/jobs/<int:job_id>/send', methods=['POST'])
@login_required
def send_email(job_id):
    try:
        if request.form.get('confirm_send') != 'yes':
            abort(400)
        if not job_finder_service.allow_action(current_user.get_id(), 'send-email', 5, 3600):
            flash('Application email sending is limited to five confirmations per hour.', 'warning')
            return redirect(url_for('main.job_finder.dashboard'))
        job = job_finder_service.get_job(job_id)
        if not job or job.get('status') != 'approved':
            abort(404)
        subject, body = _email_preview(job)
        job, audit_id = job_finder_service.begin_send(job_id, subject, body)
        ensure_cv = current_app.extensions.get('job_finder_ensure_cv')
        send_email_service = current_app.extensions.get('job_finder_send_email')
        if not ensure_cv or not send_email_service:
            raise RuntimeError('Application email service is not configured')
        with open(ensure_cv(), 'rb') as cv_file:
            cv_attachment = b64encode(cv_file.read()).decode('ascii')
        payload = {
            'from': current_app.config.get('RESEND_FROM') or 'onboarding@resend.dev',
            'to': [job['application_email']],
            'reply_to': build_job_reply_to(
                current_app.config.get('INBOX_USER') or current_app.config.get('CONTACT_EMAIL'), job_id,
            ),
            'subject': subject,
            'html': body,
            'attachments': [{'filename': 'Al-ameen_cv.pdf', 'content': cv_attachment}],
        }
        result = send_email_service(payload)
        provider_ref = result.get('id') if isinstance(result, dict) else getattr(result, 'id', None)
        job_finder_service.finish_send(audit_id, job_id, True, provider_ref=provider_ref)
        flash('Application email sent and recorded.', 'success')
    except ValueError as error:
        flash(str(error), 'warning')
    except Exception as error:  # noqa: BLE001
        logger.error('Job Finder send failed (%s)', type(error).__name__)
        if 'audit_id' in locals():
            try:
                job_finder_service.finish_send(
                    audit_id, job_id, False, error_code=type(error).__name__,
                )
            except Exception:
                logger.exception('Could not record failed Job Finder send')
        flash('The application email could not be sent. The approved draft remains available.', 'danger')
    return redirect(url_for('main.job_finder.dashboard'))
