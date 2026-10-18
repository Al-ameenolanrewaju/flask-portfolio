from typing import ClassVar

import pytest

import app as app_module
from app import app
from config import TestingConfig
from job_finder_service import DEFAULT_PREFERENCES
from models import User
from routes.job_finder import job_finder_service


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


def test_job_finder_dashboard_renders_private_preferences_and_attributions(job_client, monkeypatch):
    _authenticate(job_client, monkeypatch)
    monkeypatch.setattr(job_finder_service, 'get_preferences', lambda: DEFAULT_PREFERENCES)
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
