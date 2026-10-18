from datetime import datetime, timezone

import pytest

from job_finder_service import (
    DEFAULT_PREFERENCES,
    JobFinderService,
    parse_preferences,
)

UTC = timezone.utc  # noqa: UP017


def test_default_preferences_include_requested_role_and_send_cap():
    assert 'Python Developer' in DEFAULT_PREFERENCES['target_titles']
    assert 'Flask' in DEFAULT_PREFERENCES['keywords']
    assert DEFAULT_PREFERENCES['locations'] == ['Worldwide', 'Lagos, Nigeria']
    assert DEFAULT_PREFERENCES['remote_only'] is True
    assert DEFAULT_PREFERENCES['daily_send_cap'] == 5
    assert DEFAULT_PREFERENCES['enabled_sources'] == ['remotive', 'remoteok']


def test_preferences_form_validates_ranges_and_source_allowlist():
    preferences = parse_preferences({
        'target_titles': 'Python Developer\nFlask Developer',
        'keywords': 'Python, Flask, PostgreSQL',
        'excluded_keywords': 'senior\nprincipal',
        'locations': 'Worldwide\nLagos, Nigeria',
        'remote_only': 'on',
        'minimum_match_score': '72',
        'excluded_companies': 'Spam Co',
        'daily_send_cap': '5',
        'enabled_sources': ['remotive', 'remoteok', 'unapproved'],
    })

    assert preferences['target_titles'] == ['Python Developer', 'Flask Developer']
    assert preferences['keywords'] == ['Python', 'Flask', 'PostgreSQL']
    assert preferences['minimum_match_score'] == 72
    assert preferences['daily_send_cap'] == 5
    assert preferences['enabled_sources'] == ['remotive', 'remoteok']
    assert preferences['remote_only'] is True

    with pytest.raises(ValueError, match='between 0 and 100'):
        parse_preferences({'minimum_match_score': '101'})


def test_source_failure_does_not_prevent_other_source_jobs_from_being_stored(monkeypatch):
    good_job = {
        'source_key': 'good', 'source_name': 'Good', 'source_url': 'https://good.example/api',
        'external_id': 'g1', 'posting_url': 'https://good.example/jobs/1',
        'posting_url_key': 'https://good.example/jobs/1', 'apply_url': 'https://good.example/apply/1',
        'application_email': None, 'title': 'Python Developer', 'title_key': 'python developer',
        'company': 'Good Co', 'company_key': 'good co', 'location': 'Worldwide', 'job_type': 'full time',
        'posted_at': datetime.now(UTC), 'description': 'Needs Python.', 'keywords': ['Python'],
    }

    class Source:
        def __init__(self, jobs=None, error=None):
            self.jobs = jobs or []
            self.error = error

        def has_fresh_cache(self):
            return True

        def fetch(self):
            if self.error:
                raise self.error
            return self.jobs

    service = JobFinderService(
        connection_factory=lambda: None,
        sources={
            'broken': Source(error=TimeoutError('source timeout')),
            'good': Source([good_job]),
        },
    )
    monkeypatch.setattr(service, 'get_preferences', lambda: {
        **DEFAULT_PREFERENCES, 'enabled_sources': ['broken', 'good'],
    })
    stored = []
    monkeypatch.setattr(service, '_store_new_jobs', lambda jobs: stored.extend(jobs) or jobs)

    result = service.fetch_new_jobs()

    assert result['source_errors'] == {'broken': 'TimeoutError'}
    assert result['inserted'] == 1
    assert stored[0]['title'] == 'Python Developer'


def test_approved_draft_edits_revoke_approval_until_approved_again():
    class Cursor:
        def __init__(self):
            self.row = None
            self.update = None

        def execute(self, sql, params=None):
            if sql.startswith('SELECT status, cover_letter'):
                self.row = {'status': 'approved', 'cover_letter': 'Old letter', 'pitch': 'One\nTwo\nThree'}
            elif sql.startswith('UPDATE job_finder_jobs'):
                self.update = params

        def fetchone(self):
            return self.row

        def close(self):
            pass

    class Connection:
        def __init__(self):
            self.db_cursor = Cursor()

        def cursor(self, cursor_factory=None):
            return self.db_cursor

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    connection = Connection()
    service = JobFinderService(connection_factory=lambda: connection, sources={})

    status = service.update_review(
        4, 'save', 'Edited letter', ['Line one', 'Line two', 'Line three'], 'Check role', None,
    )

    assert status == 'drafted'
    assert connection.db_cursor.update[4] == 'drafted'
    assert connection.db_cursor.update[1] == 'Line one\nLine two\nLine three'


def test_approval_requires_complete_cover_letter_and_three_pitch_lines():
    class Cursor:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return {'status': 'drafted', 'cover_letter': None, 'pitch': None}

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    service = JobFinderService(connection_factory=Connection, sources={})

    with pytest.raises(ValueError, match='exactly three pitch lines'):
        service.update_review(4, 'approve', 'Cover letter', ['Only two', 'lines'])


def test_master_profile_missing_fields_are_marked_unknown():
    service = JobFinderService(connection_factory=lambda: None, sources={})

    profile = {'full_name': '', 'email': '', 'skills': ['Python'], 'work_history': [], 'projects': []}

    normalized = service.normalize_master_profile(profile)

    assert normalized['full_name'] == 'unknown'
    assert normalized['email'] == 'unknown'
    assert normalized['education'] == 'unknown'
    assert normalized['availability'] == 'unknown'


def test_application_pack_redacts_legal_questions_and_uses_profile_only():
    service = JobFinderService(connection_factory=lambda: None, sources={})

    class FakeGroq:
        def generate_json(self, prompt, before_request=None):
            return {
                'cover_letter': 'Dear hiring team, I am excited to apply for the Python role.',
                'email_subject': 'Python Developer application',
                'email_body': 'Hi team, I want to apply.',
                'form_answers': {
                    'why_this_company': 'Because it matches my work.',
                    'why_this_role': 'I build Python products.',
                    'biggest_project': 'Portfolio system',
                    'strengths': 'Clear communication and shipping',
                    'availability': 'Available immediately',
                    'salary_expectation': 'I can discuss during interview',
                    'work_authorization': 'needs my answer',
                },
                'linkedin_message': 'Hi, I am interested in this role.',
                'follow_up_email': 'Thanks for your time.',
                'interview_prep': {'questions': ['Tell me about your Python work.']},
                'cv_data': {
                    'name': 'Ada Lovelace',
                    'about': 'Python developer',
                    'skills': {'Python': ['Flask']},
                    'projects': [{'title': 'Portfolio', 'description': 'Built portfolio', 'technologies': ['Python']}],
                    'contact': 'ada@example.com',
                },
            }

    profile = {
        'full_name': 'Ada Lovelace',
        'email': 'ada@example.com',
        'links': {'portfolio': 'https://example.com', 'github': 'https://github.com/ada'},
        'skills': ['Python', 'Flask'],
        'projects': [{'title': 'Portfolio', 'description': 'Built portfolio', 'technologies': ['Python', 'Flask']}],
    }

    pack = service.build_application_pack({'title': 'Python Developer'}, profile, FakeGroq())

    assert 'Ada Lovelace' in pack['cover_letter']
    assert pack['answers']['salary_expectation'] == 'needs my answer'
    assert pack['answers']['work_authorization'] == 'needs my answer'
    assert 'visa' not in pack['answers']['work_authorization'].lower()


def test_tailored_cv_contains_only_profile_data():
    service = JobFinderService(connection_factory=lambda: None, sources={})

    profile = {
        'full_name': 'Ada Lovelace',
        'email': 'ada@example.com',
        'links': {'portfolio': 'https://example.com'},
        'skills': ['Python', 'Flask'],
        'projects': [{'title': 'Portfolio', 'description': 'Built a portfolio site', 'technologies': ['Python', 'Flask']}],
    }

    cv_data = service.build_tailored_cv_data({"title": "Python Developer"}, profile)

    assert cv_data['name'] == 'Ada Lovelace'
    assert cv_data['contact'] == 'ada@example.com'
    assert 'Django' not in str(cv_data)
    assert 'Senior' not in str(cv_data)
