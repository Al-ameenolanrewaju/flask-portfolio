from datetime import datetime, timezone
from typing import ClassVar

import pytest

import app as app_module
from app import app
from config import TestingConfig
from job_finder_service import DEFAULT_PREFERENCES
from models import User
from routes import job_finder as job_finder_module
from routes.job_finder import job_finder_service

UTC = timezone.utc  # noqa: UP017


@pytest.fixture
def job_client(monkeypatch):
    app.config.from_object(TestingConfig)
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def _authenticate(client, monkeypatch):
    user = User(id=99124, username='job-finder-admin', email='job-finder-admin@example.com', password='unused')
    monkeypatch.setattr(app_module.login_manager, '_user_callback', lambda user_id: user)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_job_finder_page_requires_admin_login(job_client):
    response = job_client.get('/admin/job-finder/')

    assert response.status_code == 302


def test_job_finder_inbox_requires_admin_login(job_client):
    response = job_client.get('/admin/job-finder/inbox')

    assert response.status_code == 302


def test_interview_calendar_download_is_private_and_returns_ics(job_client, monkeypatch):
    response = job_client.get('/admin/job-finder/jobs/12/interviews/7.ics')
    assert response.status_code == 302

    _authenticate(job_client, monkeypatch)
    monkeypatch.setattr(job_finder_service, 'get_job', lambda job_id: {
        'id': job_id, 'title': 'Python Developer', 'company': 'Acme',
    })
    monkeypatch.setattr(job_finder_module.interview_service, 'get', lambda job_id, event_id: {
        'id': event_id, 'uid': 'interview-7@example.test',
        'starts_at': datetime(2026, 10, 19, 8, 30, tzinfo=UTC),
        'timezone': 'Africa/Lagos', 'duration_minutes': 60,
        'location': 'Lagos office', 'meeting_url': '', 'interviewer': 'Ada',
    })

    response = job_client.get('/admin/job-finder/jobs/12/interviews/7.ics')

    assert response.status_code == 200
    assert response.mimetype == 'text/calendar'
    assert 'attachment; filename="interview-7.ics"' in response.headers['Content-Disposition']
    assert b'UID:interview-7@example.test' in response.data


def test_results_dashboard_shows_sample_size_warning(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    app.config['RESULTS_MIN_APPLICATIONS'] = '10'
    monkeypatch.setattr(job_finder_module.results_dashboard_service, 'load', lambda: [{
        'source_key': 'remotive', 'score_band': '70-79', 'score_floor': 70,
        'found_count': 15, 'applied_count': 5, 'replies_count': 2, 'responded_jobs': 1,
        'interviews_count': 0, 'rejections_count': 0, 'response_rate': 20.0,
        'median_days_to_reply': 3.5, 'reply_sample_count': 1,
    }])

    response = job_client.get('/admin/job-finder/results')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'n=5 applications' in page
    assert 'Too few results for this group: 5 applications; minimum is 10.' in page
    assert 'Apply suggested score' not in page


def test_score_recommendation_changes_preferences_only_after_explicit_post(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    app.config['RESULTS_MIN_APPLICATIONS'] = '10'
    rows = [{
        'source_key': 'remotive', 'score_band': '80-89', 'score_floor': 80,
        'found_count': 15, 'applied_count': 10, 'replies_count': 6, 'responded_jobs': 6,
        'interviews_count': 2, 'rejections_count': 1, 'response_rate': 60.0,
        'median_days_to_reply': 2.0, 'reply_sample_count': 6,
    }]
    monkeypatch.setattr(job_finder_module.results_dashboard_service, 'load', lambda: rows)
    preferences = {'minimum_match_score': 65}
    saved = []
    monkeypatch.setattr(job_finder_service, 'get_preferences', lambda: dict(preferences))
    monkeypatch.setattr(job_finder_service, 'save_preferences', saved.append)

    page = job_client.get('/admin/job-finder/results').get_data(as_text=True)
    assert 'Apply suggested score 80' in page
    assert saved == []

    response = job_client.post('/admin/job-finder/results/apply-suggestion', data={
        'minimum_match_score': '80',
    })

    assert response.status_code == 302
    assert saved[0]['minimum_match_score'] == 80




def test_job_finder_dashboard_renders_private_preferences_and_attributions(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    monkeypatch.setattr(job_finder_service, 'get_preferences', lambda: DEFAULT_PREFERENCES)
    monkeypatch.setattr(job_finder_service, 'job_status_counts', lambda: {
        'found': 1, 'drafted': 0, 'approved': 0, 'applied': 0,
        'interview': 0, 'rejected': 0, 'ignored': 0, 'total': 1,
    })
    monkeypatch.setattr(job_finder_service, 'review_queue_count', lambda minimum_score: 1)
    monkeypatch.setattr(job_finder_service, 'list_jobs', lambda **kwargs: [{
        'id': 1, 'title': 'Flask Developer', 'company': 'Example', 'location': 'Worldwide',
        'score': None, 'match_reason': None, 'source_name': 'Remotive',
        'source_url': 'https://remotive.com/remote-jobs/api', 'posting_url': 'https://remotive.com/jobs/1',
        'apply_url': 'https://remotive.com/jobs/1', 'cover_letter': None, 'pitch': None,
        'notes': '', 'follow_up_date': None, 'job_type': 'Full time',
        'posted_at': None, 'status': 'found',
    }])
    monkeypatch.setattr(job_finder_service, 'recent_source_runs', list)

    response = job_client.get('/admin/job-finder/')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Python Developer' in page
    assert 'Remotive' in page
    assert 'Automated matches can be wrong' in page
    assert 'https://remotive.com/jobs/1' in page


def test_job_finder_dashboard_filters_and_paginates_all_saved_jobs(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    counts = {
        'found': 30, 'drafted': 0, 'approved': 55, 'applied': 2,
        'interview': 1, 'rejected': 0, 'ignored': 4, 'total': 92,
    }
    calls = []
    monkeypatch.setattr(job_finder_service, 'get_preferences', lambda: DEFAULT_PREFERENCES)
    monkeypatch.setattr(job_finder_service, 'job_status_counts', lambda: counts)
    monkeypatch.setattr(job_finder_service, 'review_queue_count', lambda minimum_score: 7)
    monkeypatch.setattr(job_finder_service, 'list_jobs', lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(job_finder_service, 'recent_source_runs', list)

    response = job_client.get('/admin/job-finder/?status=approved&page=2')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert calls == [{'status': 'approved', 'limit': 25, 'offset': 25}]
    assert 'Showing 26–50 of 55' in page
    assert 'Approved</h2>' in page
    assert 'Page 2 of 3' in page


def test_job_finder_dashboard_defaults_to_minimum_score_review_queue(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    counts = {
        'found': 30, 'drafted': 3, 'approved': 5, 'applied': 2,
        'interview': 1, 'rejected': 0, 'ignored': 4, 'total': 45,
    }
    calls = []
    monkeypatch.setattr(job_finder_service, 'get_preferences', lambda: DEFAULT_PREFERENCES)
    monkeypatch.setattr(job_finder_service, 'job_status_counts', lambda: counts)
    monkeypatch.setattr(job_finder_service, 'review_queue_count', lambda minimum_score: 2)
    monkeypatch.setattr(job_finder_service, 'list_jobs', lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(job_finder_service, 'recent_source_runs', list)

    response = job_client.get('/admin/job-finder/')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert calls == [{'limit': 25, 'offset': 0, 'review_min_score': DEFAULT_PREFERENCES['minimum_match_score']}]
    assert 'Review queue' in page
    assert 'Showing 1–2 of 2' in page
    assert 'All jobs' in page


def test_job_finder_preferences_post_saves_valid_values(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    saved = []
    monkeypatch.setattr(job_finder_service, 'save_preferences', saved.append)

    response = job_client.post('/admin/job-finder/preferences', data={
        'target_titles': 'Python Developer\nFlask Developer',
        'keywords': 'Python\nFlask',
        'excluded_keywords': 'senior',
        'locations': 'Worldwide\nLagos, Nigeria',
        'remote_only': 'on',
        'minimum_match_score': '70',
        'excluded_companies': 'Spam Corp',
        'daily_send_cap': '5',
        'enabled_sources': ['remotive', 'remoteok'],
    })

    assert response.status_code == 302
    assert saved[0]['minimum_match_score'] == 70
    assert saved[0]['daily_send_cap'] == 5
    assert saved[0]['enabled_sources'] == ['remotive', 'remoteok']


def test_job_finder_run_now_checks_rate_limit_and_scheduler(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    monkeypatch.setattr(job_finder_service, 'allow_action', lambda *args: True)

    class Scheduler:
        jobs: ClassVar[dict[str, dict]] = {'job-finder-fetch': {}}

        def __init__(self):
            self.runs = []

        def run_job(self, name):
            self.runs.append(name)
            return True

    scheduler = Scheduler()
    original_scheduler = app.extensions.get('job_scheduler')
    app.extensions['job_scheduler'] = scheduler
    try:
        response = job_client.post('/admin/job-finder/run-now')
        assert response.status_code == 302
        assert scheduler.runs == ['job-finder-fetch']
    finally:
        if original_scheduler is None:
            app.extensions.pop('job_scheduler', None)
        else:
            app.extensions['job_scheduler'] = original_scheduler


def test_job_finder_run_now_rejects_rate_limited_request(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    monkeypatch.setattr(job_finder_service, 'allow_action', lambda *args: False)

    class Scheduler:
        jobs: ClassVar[dict[str, dict]] = {'job-finder-fetch': {}}

        def run_job(self, name):
            pytest.fail('rate-limited request must not run the scheduled job')

    original_scheduler = app.extensions.get('job_scheduler')
    app.extensions['job_scheduler'] = Scheduler()
    try:
        response = job_client.post('/admin/job-finder/run-now', follow_redirects=True)
        assert response.status_code == 200
        assert b'limited to three requests per hour' in response.data
    finally:
        if original_scheduler is None:
            app.extensions.pop('job_scheduler', None)
        else:
            app.extensions['job_scheduler'] = original_scheduler


def test_job_finder_post_is_protected_by_csrf(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    app.config['WTF_CSRF_ENABLED'] = True

    response = job_client.post('/admin/job-finder/preferences', data={'target_titles': 'Python Developer'})

    assert response.status_code == 400
