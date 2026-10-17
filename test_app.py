import pytest
import base64
import json
from unittest.mock import Mock
import app as app_module
from app import app
from config import TestingConfig
from github_client import GitHubAPIError, GitHubClient
from models import User, db





@pytest.fixture
def client():
    app.config.from_object(TestingConfig)
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_home_page(client):
    response = client.get('/')
    assert response.status_code == 200

def test_404_page(client):
    response = client.get('/nonexistent-page')
    assert response.status_code == 404

def test_admin_redirects_when_not_logged_in(client):
    response = client.get('/admin')
    assert response.status_code == 302

def test_login_with_wrong_password(client):
    response = client.post('/admin/login', data={
        'username': 'wronguser',
        'password': 'wrongpassword',
    }, follow_redirects=True)
    assert b'Invalid' in response.data

def test_contact_form_empty(client):
    response = client.post('/contact', data={
        'name': '',
        'email': '',
        'message': '',
    }, follow_redirects=True)
    assert response.status_code == 200

def test_api_projects(client):
    response = client.get('/api/v1/projects')
    assert response.status_code == 200

def test_api_projects_not_found(client):
    response = client.get('/api/v1/projects/99999')
    assert response.status_code == 404

def test_add_project_requires_login(client):
    response = client.post('/add_project', data={
        'title': 'Test Project',
        'description': 'Test description',
        'link': '#'
    }, follow_redirects=True)
    assert response.status_code == 200


def test_edit_project_get_shows_existing_values(client):
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows
            self._index = 0

        def execute(self, *args, **kwargs):
            pass

        def fetchone(self):
            return self.rows

        def close(self):
            pass

    class FakeConn:
        def __init__(self, rows):
            self.rows = rows

        def cursor(self, cursor_factory=None):
            return FakeCursor(self.rows)

        def close(self):
            pass

    with app.app_context():
        db.create_all()
        user = User.query.filter_by(username='admin').first()
        if user is None:
            user = User(username='admin', email='admin@example.com', password='pw')
            db.session.add(user)
            db.session.commit()
        user_id = user.id

    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConn({
        'id': 7,
        'title': 'My Existing Project',
        'description': 'Old description',
        'link': 'https://example.com'
    }))
    try:
        response = client.get('/edit_project/7')
        assert response.status_code == 200
        text = response.get_data(as_text=True)
        assert 'My Existing Project' in text
        assert 'Old description' in text
        assert 'https://example.com' in text
    finally:
        monkeypatch.undo()


def test_edit_imported_project_tracks_hosted_url_separately(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    statements = []

    class FakeCursor:
        def execute(self, sql, params=None):
            statements.append((sql, params))

        def fetchone(self):
            return {
                'title': 'WAJ Vtu',
                'description': '',
                'link': 'https://github.com/Al-ameenolanrewaju/WAJ-VTU',
                'homepage_url': None,
                'github_full_name': 'Al-ameenolanrewaju/WAJ-VTU',
                'edited_fields': '[]',
            }

        def close(self):
            pass

    class FakeConnection:
        def cursor(self, cursor_factory=None):
            return FakeCursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConnection())
    response = client.post('/edit_project/8', data={
        'title': 'WAJ Vtu',
        'description': '',
        'link': 'https://waj-vtu.onrender.com',
    })

    update = next(params for sql, params in statements if sql.startswith('UPDATE projects'))
    assert response.status_code == 302
    assert update[2] == 'https://waj-vtu.onrender.com'
    assert update[3] == 'https://waj-vtu.onrender.com'
    assert 'link' in json.loads(update[4])


def test_project_card_links_hosted_site_and_github_code_separately(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setattr(app_module, 'get_projects', lambda: [{
        'title': 'WAJ Vtu',
        'description': 'Project description',
        'link': 'https://waj-vtu.onrender.com',
        'homepage_url': 'https://waj-vtu.onrender.com',
        'github_full_name': 'Al-ameenolanrewaju/WAJ-VTU',
        'edited_fields': [],
        'image': '',
        'languages': ['Python'],
        'topics': [],
        'stars': 1,
        'last_pushed_at': None,
        'created_at': None,
    }])
    monkeypatch.setattr(app_module, 'get_content_from_db', lambda: {})
    monkeypatch.setattr(app_module, 'get_skills_from_table', lambda: {})

    response = client.get('/')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="https://waj-vtu.onrender.com"' in page
    assert 'href="https://github.com/Al-ameenolanrewaju/WAJ-VTU"' in page


def test_auth_login_uses_configured_credentials_when_user_missing(client):
    app.config['ADMIN_USERNAME'] = 'admin'
    app.config['ADMIN_PASSWORD'] = 'StrongPassword123'
    with app.app_context():
        User.query.filter_by(username='admin').delete()
        db.session.commit()

    response = client.post('/auth/login', data={
        'username': 'admin',
        'password': 'StrongPassword123',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin')


def test_admin_login_uses_configured_credentials_when_user_missing(client):
    app.config['ADMIN_USERNAME'] = 'admin'
    app.config['ADMIN_PASSWORD'] = 'StrongPassword123'
    with app.app_context():
        User.query.filter_by(username='admin').delete()
        db.session.commit()

    response = client.post('/admin/login', data={
        'username': 'admin',
        'password': 'StrongPassword123',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin')


def test_ensure_db_schema_creates_missing_tables(monkeypatch):
    executed = []

    class FakeCursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'DATABASE_URL', 'sqlite:///memory:')
    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConn())

    app_module.ensure_db_schema()

    assert any('CREATE TABLE IF NOT EXISTS SITE_CONTENT' in sql.upper() for sql, _ in executed)
    assert any('CREATE TABLE IF NOT EXISTS SKILLS' in sql.upper() for sql, _ in executed)


class FakeGitHubCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout):
        self.values[key] = value


def test_github_client_reads_readme_and_enriches_repo(monkeypatch):
    readme = base64.b64encode(b'# Project\n\nA useful project description.\n').decode()
    replies = {
        '/users/example/repos?type=owner&sort=pushed&per_page=100&page=1': [{
            'id': 42, 'name': 'gaming-hub', 'full_name': 'example/gaming-hub',
            'description': None, 'homepage': 'https://example.com', 'html_url': 'https://github.com/example/gaming-hub',
            'pushed_at': '2026-10-01T00:00:00Z', 'stargazers_count': 3, 'archived': False,
        }],
        '/users/example/repos?type=owner&sort=pushed&per_page=100&page=2': [],
        '/repos/example/gaming-hub/languages': {'Python': 100},
        '/repos/example/gaming-hub/topics': {'names': ['portfolio']},
        '/repos/example/gaming-hub/readme': {'content': readme},
    }
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        response = Mock(status_code=200, headers={})
        response.json.return_value = replies[url.removeprefix(GitHubClient.API_ROOT)]
        response.raise_for_status.return_value = None
        return response

    monkeypatch.setattr('github_client.requests.get', fake_get)
    repositories = GitHubClient('example', 'secret-token', FakeGitHubCache()).list_repositories()

    assert 'A useful project description.' in repositories[0]['description']
    assert repositories[0]['languages'] == {'Python': 100}
    assert repositories[0]['topics'] == ['portfolio']
    assert repositories[0]['preview_image'].endswith('/42/example/gaming-hub')
    assert all(headers['Authorization'] == 'Bearer secret-token' for _, headers, _ in calls)
    assert all(timeout == (3.05, 10) for _, _, timeout in calls)


def test_readme_description_skips_run_section_and_code_blocks():
    markdown = '''# Gaming Hub

Gaming Hub helps players find a table.

## Run Gaming Hub
[](https://github.com/Al-ameenolanrewaju/gaminghub#run-gaming-hub)
Gaming Hub runs on Flask and uses the local database.

Install the dependencies and run the server:

```sh
pip install -r requirements.txt
python manage.py
```

## Features
Players can create and join game rooms.
'''

    description = GitHubClient._readme_paragraph(markdown)

    assert 'Gaming Hub helps players find a table.' in description
    assert 'Players can create and join game rooms.' in description
    assert 'Run Gaming Hub' not in description
    assert 'install the dependencies' not in description
    assert 'pip install' not in description
    assert 'https://github.com/Al-ameenolanrewaju/gaminghub' not in description


class RecordingCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, sql, params=None):
        self.connection.statements.append((sql, params))
        if sql.startswith('SELECT id, github_repo_id, edited_fields'):
            self.rows = self.connection.existing_rows
        elif sql.startswith('SELECT github_repo_id FROM projects'):
            self.rows = []
        else:
            self.rows = []

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class RecordingConnection:
    def __init__(self, existing_rows=None):
        self.existing_rows = existing_rows or []
        self.statements = []
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        return RecordingCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def github_repo(repo_id=42):
    return {
        'id': repo_id,
        'name': 'gaming-hub',
        'full_name': 'example/gaming-hub',
        'description': 'Updated description',
        'homepage': 'https://example.com',
        'html_url': 'https://github.com/example/gaming-hub',
        'preview_image': 'https://opengraph.githubassets.com/42/example/gaming-hub',
        'languages': {'Python': 100},
        'topics': ['portfolio'],
        'stargazers_count': 9,
        'pushed_at': '2026-10-01T00:00:00Z',
        'archived': False,
        'fork': False,
    }


def authenticate_test_user(client, monkeypatch):
    user = User(id=123456, username='github-import-test', email='github-import-test@example.com', password='unused')
    monkeypatch.setattr(app_module.login_manager, '_user_callback', lambda user_id: user)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_github_import_persists_selected_repository(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    connection = RecordingConnection()
    monkeypatch.setattr(app_module, 'get_db_connection', lambda: connection)

    class FakeClient:
        def list_repositories(self, enrich=True):
            return [github_repo()]

        def enrich_repositories(self, repositories):
            return repositories

    monkeypatch.setattr(app_module, '_github_client', lambda: FakeClient())
    response = client.post('/admin/github/import', data={'repo_ids': '42'})

    insert = next((sql, params) for sql, params in connection.statements if sql.startswith('INSERT INTO projects'))
    assert response.status_code == 302
    assert insert[1][0] == 'Gaming Hub'
    assert insert[1][1] == 'Updated description'
    assert insert[1][2] == 'https://example.com'
    assert insert[1][5] == 42
    assert connection.committed


def test_sync_preserves_edited_fields_and_marks_missing_repositories(monkeypatch):
    connection = RecordingConnection([
        {'id': 1, 'github_repo_id': 42, 'edited_fields': '["title", "description", "link"]'},
        {'id': 2, 'github_repo_id': 84, 'edited_fields': '[]'},
    ])
    monkeypatch.setattr(app_module, 'get_db_connection', lambda: connection)

    imported, updated = app_module.sync_github_projects([github_repo()])

    update_sql = next(sql for sql, _ in connection.statements if sql.startswith('UPDATE projects SET') and 'WHERE id=%s' in sql)
    assert (imported, updated) == (0, 1)
    assert 'title=%s' not in update_sql
    assert 'description=%s' not in update_sql
    assert 'link=%s' not in update_sql
    assert any('github_missing=TRUE' in sql for sql, _ in connection.statements)
    assert connection.committed


def test_regular_sync_does_not_import_unselected_repository(monkeypatch):
    connection = RecordingConnection()
    monkeypatch.setattr(app_module, 'get_db_connection', lambda: connection)

    imported, updated = app_module.sync_github_projects([github_repo()])

    assert (imported, updated) == (0, 0)
    assert not any(sql.startswith('INSERT INTO projects') for sql, _ in connection.statements)


def test_github_failure_is_reported_and_public_page_uses_saved_data(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)

    class FailedClient:
        def list_repositories(self, enrich=True):
            raise GitHubAPIError('GitHub could not be reached. Your saved projects are unchanged.')

    monkeypatch.setattr(app_module, '_github_client', lambda: FailedClient())
    response = client.get('/admin/github/import')
    assert response.status_code == 200
    assert b'GitHub could not be reached' in response.data

    monkeypatch.setattr(app_module, 'get_projects', lambda: [])
    monkeypatch.setattr(app_module, 'get_content_from_db', lambda: {})
    monkeypatch.setattr(app_module, 'get_skills_from_table', lambda: {})
    assert client.get('/').status_code == 200


def test_github_client_wraps_network_failures(monkeypatch):
    import requests

    def raise_timeout(*args, **kwargs):
        raise requests.Timeout('request timed out')

    monkeypatch.setattr('github_client.requests.get', raise_timeout)
    with pytest.raises(GitHubAPIError, match='could not be reached'):
        GitHubClient('example').list_repositories()


def test_registration_is_disabled(client):
    assert client.get('/register').status_code == 404
    assert client.post('/register', data={'username': 'new', 'password': 'secret'}).status_code == 404


def test_admin_and_api_writes_require_login(client):
    assert client.post('/admin/github/sync').status_code == 302
    assert client.post('/api/v1/projects', json={'title': 'Unauthorized', 'description': 'No'}).status_code == 302
    assert client.delete('/api/v1/projects/1').status_code == 302
    assert client.get('/delete_project/1').status_code == 405


def test_contact_post_requires_csrf(client, monkeypatch):
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    response = client.post('/contact', data={'name': 'A', 'email': 'a@example.com', 'message': 'Hello'})
    assert response.status_code == 400


def test_authenticated_api_write_requires_csrf(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    response = client.post('/api/v1/projects', json={'title': 'Project', 'description': 'Description'})
    assert response.status_code == 400