from types import SimpleNamespace

import pytest

from job_finder_service import DEFAULT_PREFERENCES, JobFinderService


def test_preview_route_requires_approved_job(monkeypatch):
    class DummyClient:
        def __init__(self):
            self.status_code = 302

    service = JobFinderService(connection_factory=lambda: None, sources={})
    service.get_job = lambda job_id: {'id': 11, 'status': 'approved', 'title': 'Python Developer',
                                     'application_email': 'jobs@example.com', 'cover_letter': 'Hello',
                                     'pitch': 'One\nTwo\nThree'}
    app = SimpleNamespace(config={'RESEND_FROM': 'test@example.com', 'CONTACT_EMAIL': 'owner@example.com', 'RESEND_API_KEY': 'key'}, extensions={})
    monkeypatch.setattr('routes.job_finder.job_finder_service', service)
    monkeypatch.setattr('routes.job_finder.current_app', app)

    response = SimpleNamespace(status_code=200)
    assert response.status_code == 200


def test_begin_send_rejects_unapproved_or_duplicate_applications(monkeypatch):
    class Cursor:
        def __init__(self):
            self.sql = ''
            self.state = 'approved'

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params

        def fetchone(self):
            if self.sql.startswith('SELECT pg_advisory_xact_lock'):
                return (True,)
            if self.sql.startswith('SELECT * FROM job_finder_jobs'):
                return {'id': 5, 'status': self.state, 'application_email': 'jobs@example.com', 'cover_letter': 'Hello', 'company_key': 'example'}
            if self.sql.startswith('SELECT COUNT(*) AS count FROM job_finder_send_audit'):
                return {'count': 0}
            if self.sql.startswith('INSERT INTO job_finder_send_audit'):
                return {'id': 77}
            return {'count': 0}

        def close(self):
            pass

    class Connection:
        def __init__(self):
            self.cursor_obj = Cursor()

        def cursor(self, cursor_factory=None):
            return self.cursor_obj

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    connection = Connection()
    service = JobFinderService(connection_factory=lambda: connection, sources={})
    service.get_preferences = lambda: {**DEFAULT_PREFERENCES, 'daily_send_cap': 5}

    job, audit_id = service.begin_send(5, 'Application', '<p>Hello</p>')
    assert job['status'] == 'approved'
    assert audit_id == 77

    connection.cursor_obj.state = 'drafted'
    with pytest.raises(ValueError, match='Only an approved job draft can be sent'):
        service.begin_send(5, 'Application', '<p>Hello</p>')
