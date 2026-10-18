from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import job_finder_sources as sources


def test_remotive_adapter_normalizes_fields_and_caches(monkeypatch):
    response = SimpleNamespace(
        json=lambda: {'jobs': [{
            'id': 23,
            'title': 'Python Backend Developer',
            'company_name': 'Example Inc',
            'url': 'https://remotive.com/remote-jobs/software-dev/python-backend-23?utm_source=feed',
            'publication_date': '2026-10-17T10:00:00Z',
            'candidate_required_location': 'Worldwide',
            'job_type': 'full_time',
            'description': '<a href="mailto:jobs@example.com">Apply</a>',
        }]},
        raise_for_status=Mock(),
    )
    request = Mock(return_value=response)
    monkeypatch.setattr(sources, 'request_with_retries', request)
    source = sources.RemotiveSource()

    jobs = source.fetch()
    second = source.fetch()

    assert len(jobs) == 1
    assert jobs[0]['source_name'] == 'Remotive'
    assert jobs[0]['posting_url'] == 'https://remotive.com/remote-jobs/software-dev/python-backend-23?utm_source=feed'
    assert jobs[0]['posting_url_key'] == 'https://remotive.com/remote-jobs/software-dev/python-backend-23'
    assert jobs[0]['company_key'] == 'example inc'
    assert jobs[0]['location'] == 'Worldwide'
    assert jobs[0]['application_email'] == 'jobs@example.com'
    assert jobs[0]['posted_at'].isoformat() == '2026-10-17T10:00:00+00:00'
    assert second == jobs
    request.assert_called_once()
    assert request.call_args.kwargs['timeout'] == (3.05, 15)


def test_remoteok_adapter_ignores_legal_metadata_and_normalizes_posts(monkeypatch):
    response = SimpleNamespace(
        json=lambda: [
            {'legal': 'Link to the source and mention Remote OK.'},
            {
                'id': 'r-1', 'position': 'Flask Developer', 'company': 'Remote Co',
                'url': 'https://remoteok.com/remote-jobs/flask-dev-r-1',
                'apply_url': 'https://remoteok.com/remote-jobs/flask-dev-r-1/apply',
                'date': '2026-10-17T10:00:00+00:00', 'location': 'Worldwide',
                'tags': ['python', 'flask'], 'description': 'Build APIs.',
            },
        ],
        raise_for_status=Mock(),
    )
    monkeypatch.setattr(sources, 'request_with_retries', Mock(return_value=response))

    jobs = sources.RemoteOKSource().fetch()

    assert len(jobs) == 1
    assert jobs[0]['source_key'] == 'remoteok'
    assert jobs[0]['source_url'] == 'https://remoteok.com/api'
    assert jobs[0]['apply_url'].endswith('/apply')
    assert jobs[0]['keywords'] == ['python', 'flask']
    assert jobs[0]['posted_at'].isoformat() == '2026-10-17T10:00:00+00:00'


def test_deduplicate_jobs_by_canonical_url_and_company_title():
    first = {
        'posting_url': 'https://example.com/jobs/1?utm_campaign=x',
        'company': 'Example Co', 'title': 'Python Developer',
    }
    same_url = {
        'posting_url': 'https://example.com/jobs/1#apply',
        'company': 'Different Source', 'title': 'Different Title',
    }
    same_company_title = {
        'posting_url': 'https://other.example/jobs/2',
        'company': 'EXAMPLE CO', 'title': ' python   developer ',
    }
    unique = {'posting_url': 'https://other.example/jobs/3', 'company': 'Example Co', 'title': 'Flask Developer'}

    result = sources.deduplicate_jobs([first, same_url, same_company_title, unique])

    assert result == [first, unique]


def test_source_failure_is_wrapped_and_does_not_poison_cache(monkeypatch):
    request = Mock(side_effect=requests.Timeout('timed out'))
    monkeypatch.setattr(sources, 'request_with_retries', request)
    source = sources.RemoteOKSource()

    with pytest.raises(sources.JobSourceError, match='RemoteOK feed request failed'):
        source.fetch()

    assert source._cached_jobs is None
    request.assert_called_once()
