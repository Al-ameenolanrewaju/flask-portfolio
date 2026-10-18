import hashlib
import hmac
import json

import pytest

import app as app_module
from app import app
from config import TestingConfig
from github_webhooks import verify_github_signature

SECRET = 'webhook-test-secret'
REPOSITORY = {
    'id': 55,
    'name': 'demo-app',
    'full_name': 'Al-ameenolanrewaju/demo-app',
    'owner': {'login': 'Al-ameenolanrewaju'},
    'html_url': 'https://github.com/Al-ameenolanrewaju/demo-app',
    'homepage': 'https://demo-app.onrender.com',
    'description': '',
    'pushed_at': '2026-10-18T12:00:00Z',
    'stargazers_count': 1,
    'archived': False,
}


@pytest.fixture
def client(monkeypatch):
    app.config.from_object(TestingConfig)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    monkeypatch.setitem(app.config, 'GITHUB_WEBHOOK_SECRET', SECRET)
    monkeypatch.setitem(app.config, 'GITHUB_USERNAME', 'Al-ameenolanrewaju')
    with app.test_client() as test_client:
        yield test_client


def signed_headers(payload, event='push'):
    body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(SECRET.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return body, {
        'Content-Type': 'application/json',
        'X-GitHub-Event': event,
        'X-Hub-Signature-256': f'sha256={signature}',
    }


def test_signature_verifier_requires_correct_hmac():
    body = b'{"ref":"refs/heads/main"}'
    signature = 'sha256=' + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    assert verify_github_signature(body, signature, SECRET)
    assert not verify_github_signature(body, '', SECRET)
    assert not verify_github_signature(body, 'sha256=' + ('0' * 64), SECRET)
    assert not verify_github_signature(body, signature, '')


@pytest.mark.parametrize('signature', ['', 'sha256=' + ('0' * 64)])
def test_webhook_rejects_unsigned_or_invalid_requests(client, signature):
    body = json.dumps({'repository': REPOSITORY}).encode('utf-8')
    response = client.post(
        '/webhooks/github',
        data=body,
        content_type='application/json',
        headers={'X-GitHub-Event': 'push', 'X-Hub-Signature-256': signature},
    )

    assert response.status_code == 401


def test_signed_push_is_csrf_exempt_and_syncs_only_its_repo(client, monkeypatch):
    calls = []

    class FakeGitHubClient:
        def enrich_repositories(self, repositories):
            return [{**repositories[0], 'languages': {'Python': 100}, 'topics': ['portfolio']}]

    def sync(repositories, mark_missing, import_new):
        calls.append((repositories, mark_missing, import_new))
        return 0, 1

    monkeypatch.setattr(app_module, '_github_client', lambda: FakeGitHubClient())
    monkeypatch.setattr(app_module, 'sync_github_projects', sync)
    body, headers = signed_headers({'repository': REPOSITORY})

    response = client.post('/webhooks/github', data=body, headers=headers)

    assert response.status_code == 200
    assert len(calls) == 1
    assert [repo['id'] for repo in calls[0][0]] == [55]
    assert calls[0][1:] == (False, False)


def test_repository_created_event_can_import_new_repository(client, monkeypatch):
    calls = []

    class FakeGitHubClient:
        def enrich_repositories(self, repositories):
            return [{**repositories[0], 'languages': {}, 'topics': []}]

    def sync(repositories, mark_missing, import_new):
        calls.append((repositories, mark_missing, import_new))
        return 1, 0

    monkeypatch.setattr(app_module, '_github_client', lambda: FakeGitHubClient())
    monkeypatch.setattr(app_module, 'sync_github_projects', sync)
    body, headers = signed_headers({'action': 'created', 'repository': REPOSITORY}, event='repository')

    response = client.post('/webhooks/github', data=body, headers=headers)

    assert response.status_code == 200
    assert calls[0][1:] == (False, True)


def test_repository_deleted_event_marks_only_that_repo_missing(client, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, 'mark_github_repository_missing', calls.append)
    body, headers = signed_headers({'action': 'deleted', 'repository': REPOSITORY}, event='repository')

    response = client.post('/webhooks/github', data=body, headers=headers)

    assert response.status_code == 200
    assert calls == [55]
