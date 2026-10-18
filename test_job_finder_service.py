from datetime import datetime, timezone

import pytest

from job_finder_service import (
    DEFAULT_PREFERENCES,
    JobFinderService,
    parse_preferences,
)


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
        'posted_at': datetime.now(timezone.utc), 'description': 'Needs Python.', 'keywords': ['Python'],
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
