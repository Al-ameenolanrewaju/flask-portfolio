import base64
import json
from typing import ClassVar
from unittest.mock import Mock

import pytest

import app as app_module
from app import app
from config import TestingConfig
from github_client import GitHubAPIError, GitHubClient
from models import User, db


@pytest.fixture
def client(request):
    app.config.from_object(TestingConfig)
    app.config['TESTING'] = True
    with app.test_client() as client:
        client.environ_base['REMOTE_ADDR'] = f"192.0.2.{abs(hash(request.node.nodeid)) % 254 + 1}"
        yield client

def test_home_page(client):
    response = client.get('/')
    assert response.status_code == 200


def test_homepage_contact_csrf_token_is_not_cached_and_can_be_submitted(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    response = client.get('/')
    page = response.get_data(as_text=True)
    token = page.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]

    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    submission = client.post('/contact', data={
        'csrf_token': token, 'website': 'bot',
    })
    assert submission.status_code == 302


def test_homepage_shows_one_ai_rewritten_project_description(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setattr(app_module, 'get_projects', lambda: [{
        'title': 'Verbose repo', 'description': 'The original repository description is very long.',
        'ai_summary': 'A concise AI rewrite.', 'ai_description': 'A longer AI description.',
        'image': None, 'link': 'https://github.com/example/repo', 'homepage_url': None,
        'github_full_name': 'example/repo', 'edited_fields': [], 'languages': [], 'topics': [],
        'stars': 3, 'last_pushed_at': None, 'created_at': None, 'demo_link_status': None,
        'ai_case_study_problem': '', 'ai_case_study_built': '', 'ai_case_study_result': '',
    }])
    monkeypatch.setattr(app_module, 'get_content_from_db', dict)
    monkeypatch.setattr(app_module, 'get_skills_from_table', dict)
    monkeypatch.setattr(app_module, 'get_auto_skills_from_projects', dict)

    response = client.get('/')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'A longer AI description.' in page
    assert 'A concise AI rewrite.' not in page
    assert 'The original repository description is very long.' not in page


def test_groq_budget_reserves_requests_for_configured_reply_inbox(monkeypatch):
    claims = []

    class Cursor:
        def __init__(self):
            self.sql = ''
            self.params = None

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params
            if sql.startswith('INSERT INTO groq_usage'):
                claims.append(params[1])

        def fetchone(self):
            return (self.params[1],) if self.sql.startswith('INSERT INTO groq_usage') else None

        def close(self):
            pass

    class Connection:
        def __init__(self):
            self.db_cursor = Cursor()

        def cursor(self):
            return self.db_cursor

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', Connection)
    monkeypatch.setattr(app_module, 'send_whatsapp_alert', lambda message: None)
    for key, value in {
        'GROQ_DAILY_REQUEST_CAP': '10',
        'GROQ_REPLY_RESERVED_REQUESTS': '2',
        'INBOX_IMAP_HOST': 'imap.example.test',
        'INBOX_USER': 'inbox@example.test',
        'INBOX_PASSWORD': 'test-password',
    }.items():
        monkeypatch.setitem(app.config, key, value)

    assert app_module._claim_groq_api_request() is True
    assert app_module._claim_groq_api_request('reply') is True
    assert claims == [8, 10]


def test_auto_skills_count_distinct_projects_case_insensitively():
    skills = app_module.build_auto_skills([
        {'languages': '["Python", "JavaScript"]', 'topics': '["flask", "web"]'},
        {'languages': ['python', 'TypeScript'], 'topics': ['Flask', 'api']},
        {'languages': 'invalid', 'topics': ['api', '']},
    ])

    languages = {item['name'].casefold(): item['project_count'] for item in skills['Languages']}
    topics = {item['name'].casefold(): item['project_count'] for item in skills['Topics']}
    assert languages == {'python': 2, 'javascript': 1, 'typescript': 1}
    assert topics == {'flask': 2, 'api': 2, 'web': 1}


def test_homepage_shows_generated_counts_with_manual_skills(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setattr(app_module, 'get_projects', list)
    monkeypatch.setattr(app_module, 'get_content_from_db', dict)
    monkeypatch.setattr(app_module, 'get_skills_from_table', lambda: {'Hand-edited': ['Custom skill']})
    monkeypatch.setattr(app_module, 'get_auto_skills_from_projects', lambda: {
        'Topics': [{'name': 'Flask', 'project_count': 4}],
    })

    response = client.get('/')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Custom skill' in page
    assert 'Flask: 4 projects' in page


def test_cv_pdf_is_cached_and_regenerated_when_site_data_changes(client, monkeypatch, tmp_path):
    data = {
        'name': 'Al-ameen Olanrewaju',
        'about': 'Builds web applications.',
        'manual_skills': {'Backend': ['Python']},
        'auto_skills': {'Topics': [{'name': 'Flask', 'project_count': 2}]},
        'projects': [{'title': 'Portfolio', 'description': 'A portfolio.', 'technologies': ['Flask']}],
        'contact': 'hello@example.com',
    }
    monkeypatch.setattr(app_module, '_cv_data', lambda: data)
    monkeypatch.setattr(app_module, 'CV_PDF_PATH', str(tmp_path / 'Al-ameen_cv.pdf'))
    monkeypatch.setattr(app_module, '_cv_cache_hash', None)
    original_build = app_module._build_cv_pdf
    generated = []

    def build(data_to_render):
        generated.append(data_to_render['about'])
        return original_build(data_to_render)

    monkeypatch.setattr(app_module, '_build_cv_pdf', build)
    first = client.get('/cv.pdf')
    second = client.get('/cv.pdf')
    data['about'] = 'Builds reliable web applications.'
    third = client.get('/cv.pdf')

    assert first.status_code == second.status_code == third.status_code == 200
    assert first.data.startswith(b'%PDF')
    assert len(generated) == 2
    assert generated == ['Builds web applications.', 'Builds reliable web applications.']


def test_404_page(client):
    response = client.get('/nonexistent-page')
    assert response.status_code == 404

def test_admin_redirects_when_not_logged_in(client):
    response = client.get('/admin')
    assert response.status_code == 302


def test_admin_has_direct_services_editor_link(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setattr(app_module, 'ensure_db_schema', lambda: None)

    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return []

        def close(self):
            pass

    class FakeConnection:
        def cursor(self, cursor_factory=None):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConnection())
    response = client.get('/admin')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/admin/edit_content#services-section"' in page


def test_homepage_renders_services_beyond_four(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setattr(app_module, 'get_projects', list)
    monkeypatch.setattr(app_module, 'get_content_from_db', lambda: {
        'service_5': {'title': 'Fifth Service', 'content': 'Beyond the old limit.'},
        'service_8': {'title': 'Eighth Service', 'content': 'Still supported.'},
    })
    monkeypatch.setattr(app_module, 'get_skills_from_table', dict)

    response = client.get('/')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Fifth Service' in page
    assert 'Eighth Service' in page


def test_services_editor_saves_service_five(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setattr(app_module, 'ensure_db_schema', lambda: None)
    statements = []

    class FakeCursor:
        def execute(self, sql, params=None):
            statements.append((sql, params))

        def fetchone(self):
            return None

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
    response = client.post('/admin/edit_content', data={
        'service_5_title': 'Fifth Service',
        'service_5_content': 'The fifth service description.',
    })

    assert response.status_code == 302
    assert any(
        sql.startswith('INSERT INTO site_content') and params[0] == 'service_5'
        for sql, params in statements
    )


def test_services_editor_deletes_removed_saved_service(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setattr(app_module, 'ensure_db_schema', lambda: None)
    statements = []

    class FakeCursor:
        def execute(self, sql, params=None):
            statements.append((sql, params))

        def fetchone(self):
            return None

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
    response = client.post('/admin/edit_content', data={'remove_service_ids': '5'})

    assert response.status_code == 302
    assert ('DELETE FROM site_content WHERE section_name=%s', ('service_5',)) in statements


def test_services_editor_loads_existing_service_above_four(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setattr(app_module, 'ensure_db_schema', lambda: None)

    class FakeCursor:
        def execute(self, sql, params=None):
            self.rows = [{
                'id': 8,
                'section_name': 'service_8',
                'title': 'Eighth Service',
                'content': 'Loaded from storage.',
                'file': '',
            }] if sql == 'SELECT * FROM site_content' else []

        def fetchall(self):
            return self.rows

        def close(self):
            pass

    class FakeConnection:
        def cursor(self, cursor_factory=None):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConnection())
    response = client.get('/admin/edit_content')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="service_8_title"' in page
    assert 'Eighth Service' in page

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
    monkeypatch.setattr(app_module, 'get_content_from_db', dict)
    monkeypatch.setattr(app_module, 'get_skills_from_table', dict)

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

    def fake_get(method, url, headers, timeout):
        calls.append((url, headers, timeout))
        response = Mock(status_code=200, headers={})
        response.json.return_value = replies[url.removeprefix(GitHubClient.API_ROOT)]
        response.raise_for_status.return_value = None
        return response

    monkeypatch.setattr('github_client.request_with_retries', fake_get)
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


def test_admin_scheduled_jobs_page_and_run_now(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setattr(app_module.job_scheduler, 'statuses', lambda: [{
        'job_name': 'daily-github-sync',
        'last_run_at': None,
        'status': 'never',
        'next_run_at': None,
        'last_error': None,
        'interval': app_module.timedelta(days=1),
    }])
    monkeypatch.setattr(app_module.job_scheduler, 'run_job', lambda job_name: True)

    page = client.get('/admin/jobs')
    response = client.post('/admin/jobs/daily-github-sync/run')

    assert page.status_code == 200
    assert 'Daily Github Sync' in page.get_data(as_text=True)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin/jobs')


def test_link_check_saves_health_and_alerts_only_on_new_breakage(monkeypatch):
    project = {
        'id': 9,
        'title': 'Demo project',
        'link': 'https://demo.example',
        'homepage_url': 'https://demo.example',
        'github_full_name': 'owner/project',
        'demo_link_status': 'ok',
        'repo_link_status': 'ok',
    }
    updates = []
    alerts = []

    class Cursor:
        def execute(self, sql, params=None):
            if sql.startswith('UPDATE projects'):
                updates.append(params)
                project['demo_link_status'] = params[0]
                project['repo_link_status'] = params[2]

        def fetchall(self):
            return [project]

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())
    monkeypatch.setattr(app_module, 'check_link', lambda url: 'broken' if 'demo.example' in url else 'ok')
    monkeypatch.setattr(app_module, 'send_whatsapp_alert', alerts.append)

    result = app_module.check_project_links()
    app_module.check_project_links()

    assert result == {'checked': 1, 'new_failures': 1}
    assert len(updates) == 2
    assert updates[0][0] == 'broken'
    assert updates[0][2] == 'ok'
    assert len(alerts) == 1
    assert 'demo.example' in alerts[0]


def test_homepage_hides_broken_live_demo_link(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setattr(app_module, 'get_projects', lambda: [{
        'id': 1, 'title': 'Broken demo', 'description': 'Unavailable', 'link': 'https://demo.example',
        'homepage_url': 'https://demo.example', 'github_full_name': 'owner/project',
        'edited_fields': [], 'languages': [], 'topics': [], 'stars': 0, 'image': '',
        'demo_link_status': 'broken', 'created_at': None, 'last_pushed_at': None,
    }])
    monkeypatch.setattr(app_module, 'get_content_from_db', dict)
    monkeypatch.setattr(app_module, 'get_skills_from_table', dict)
    monkeypatch.setattr(app_module, 'get_auto_skills_from_projects', dict)

    response = client.get('/')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Open live site for Broken demo' not in page
    assert 'View source code for Broken demo' in page


def test_og_route_generates_and_caches_project_preview(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setattr(app_module, 'get_projects', lambda: [{
        'title': 'Gaming Hub', 'languages': ['Python'], 'topics': ['Flask'],
    }])
    generated = []
    original_generator = app_module.create_og_image

    def generate(title, technologies):
        generated.append((title, technologies))
        return original_generator(title, technologies)

    monkeypatch.setattr(app_module, 'create_og_image', generate)
    first = client.get('/og/gaming-hub.png')
    second = client.get('/og/gaming-hub.png')

    assert first.status_code == second.status_code == 200
    assert first.mimetype == 'image/png'
    assert len(generated) == 1
    assert generated[0] == ('Gaming Hub', ['Python', 'Flask'])


def test_homepage_sets_project_open_graph_image(client, monkeypatch):
    app_module.cache.clear()
    monkeypatch.setattr(app_module, 'get_projects', lambda: [{
        'title': 'Gaming Hub', 'description': 'Project', 'link': '', 'homepage_url': None,
        'github_full_name': None, 'edited_fields': [], 'languages': [], 'topics': [],
        'stars': 0, 'image': '', 'created_at': None, 'last_pushed_at': None,
    }])
    monkeypatch.setattr(app_module, 'get_content_from_db', dict)
    monkeypatch.setattr(app_module, 'get_skills_from_table', dict)
    monkeypatch.setattr(app_module, 'get_auto_skills_from_projects', dict)

    response = client.get('/')

    assert response.status_code == 200
    assert '/og/gaming-hub.png' in response.get_data(as_text=True)


def test_admin_shows_broken_link_warning(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setattr(app_module, 'ensure_db_schema', lambda: None)
    project = {
        'id': 5, 'title': 'Broken demo', 'description': 'Unavailable', 'github_full_name': 'owner/project',
        'demo_link_status': 'broken', 'repo_link_status': 'ok', 'github_missing': False,
        'github_archived': False, 'stars': 1, 'is_visible': True, 'is_pinned': False, 'sort_order': 0,
    }

    class Cursor:
        rows: ClassVar[list] = []

        def execute(self, sql, params=None):
            self.rows = [project] if sql.startswith('SELECT * FROM projects') else []

        def fetchall(self):
            return self.rows

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())

    response = client.get('/admin')

    assert response.status_code == 200
    assert 'Demo link broken' in response.get_data(as_text=True)


def test_screenshot_refresh_saves_a_fallback_card_when_api_is_unconfigured(monkeypatch):
    from io import BytesIO

    from PIL import Image

    project = {
        'id': 17, 'title': 'Card project', 'description': 'Generated preview',
        'link': 'https://demo.example', 'homepage_url': None, 'github_full_name': None,
        'languages': '["Python"]', 'topics': '["flask"]', 'edited_fields': '[]',
    }
    stored = {}

    class Cursor:
        def execute(self, sql, params=None):
            if sql.startswith('INSERT INTO project_screenshots'):
                stored.update({'project_id': params[0], 'image_data': params[1], 'source': params[2]})

        def fetchall(self):
            return [project]

        def fetchone(self):
            return None

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())
    monkeypatch.setattr(app_module, '_screenshot_api_provider', lambda: None)

    result = app_module.refresh_project_screenshots()

    with Image.open(BytesIO(stored['image_data'])) as image:
        assert image.format == 'WEBP'
        assert image.size == (1280, 720)
    assert result == {'generated': 1, 'api_failures': 0}
    assert stored['source'] == 'fallback'


def test_screenshot_quota_exhaustion_stops_api_calls_and_alerts_once(monkeypatch):
    projects = [
        {
            'id': project_id, 'title': f'Project {project_id}', 'description': '',
            'link': f'https://demo{project_id}.example', 'homepage_url': None, 'github_full_name': None,
            'languages': '[]', 'topics': '[]', 'edited_fields': '[]',
        }
        for project_id in (1, 2)
    ]
    saves = []
    alerts = []
    calls = []
    class Cursor:
        def __init__(self):
            self.next_row = None

        def execute(self, sql, params=None):
            if sql.startswith('INSERT INTO screenshot_usage'):
                self.next_row = (1,)
            elif sql.startswith('UPDATE screenshot_usage'):
                self.next_row = ('2026-10-01',)
            elif sql.startswith('INSERT INTO project_screenshots'):
                saves.append(params)

        def fetchall(self):
            return projects

        def fetchone(self):
            row = self.next_row
            self.next_row = None
            return row

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    class Provider:
        def capture(self, url):
            calls.append(url)
            raise app_module.ScreenshotQuotaExceeded('free quota reached')

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())
    monkeypatch.setattr(app_module, '_screenshot_api_provider', lambda: Provider())
    monkeypatch.setattr(app_module, 'send_whatsapp_alert', alerts.append)

    result = app_module.refresh_project_screenshots()

    assert result == {'generated': 2, 'api_failures': 0}
    assert calls == ['https://demo1.example']
    assert len(alerts) == 1
    assert len(saves) == 2
    assert all(params[2] == 'fallback' for params in saves)


def test_screenshot_api_never_receives_private_project_urls(monkeypatch):
    project = {
        'id': 18, 'title': 'Local test', 'description': '', 'link': 'http://127.0.0.1/private',
        'homepage_url': None, 'github_full_name': None, 'languages': '[]', 'topics': '[]', 'edited_fields': '[]',
    }
    saved = []

    class Cursor:
        def execute(self, sql, params=None):
            if sql.startswith('INSERT INTO project_screenshots'):
                saved.append(params)

        def fetchall(self):
            return [project]

        def fetchone(self):
            return None

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    class Provider:
        def capture(self, url):
            raise AssertionError('Private URLs must not reach ScreenshotOne')

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())
    monkeypatch.setattr(app_module, '_screenshot_api_provider', lambda: Provider())

    result = app_module.refresh_project_screenshots()

    assert result == {'generated': 1, 'api_failures': 0}
    assert saved[0][2] == 'fallback'


def test_screenshot_refresh_uses_github_repository_url_without_homepage(monkeypatch):
    project = {
        'id': 19, 'title': 'Repository only', 'description': '',
        'link': 'https://github.com/example/repository', 'homepage_url': None,
        'github_full_name': 'example/repository', 'languages': '[]', 'topics': '[]',
        'edited_fields': '[]',
    }
    captured = []
    saved = []

    class Cursor:
        def execute(self, sql, params=None):
            if sql.startswith('INSERT INTO project_screenshots'):
                saved.append(params)

        def fetchall(self):
            return [project]

        def fetchone(self):
            return None

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    class Provider:
        def capture(self, url):
            captured.append(url)
            return b'captured image'

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())
    monkeypatch.setattr(app_module, '_screenshot_api_provider', lambda: Provider())
    monkeypatch.setattr(app_module, '_reserve_screenshot_api_request', lambda: (True, False))
    monkeypatch.setattr(app_module, 'normalize_webp', lambda image: image)

    result = app_module.refresh_project_screenshots()

    assert result == {'generated': 1, 'api_failures': 0}
    assert captured == ['https://github.com/example/repository']
    assert saved[0][2] == 'screenshotone'


def test_admin_can_refresh_one_project_screenshot(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    queued = []

    class FakeExecutor:
        def submit(self, function, *args):
            queued.append((function, args))

    monkeypatch.setattr(app_module, 'screenshot_executor', FakeExecutor())

    response = client.post('/admin/projects/19/refresh-screenshot')

    assert response.status_code == 302
    assert response.location.endswith('/admin')
    assert queued == [(app_module._refresh_project_screenshot_in_background, (19,))]


def test_ai_draft_must_be_approved_before_public_data_loader_exposes_it(monkeypatch):
    projects = [
        {'id': 11, 'title': 'Approved', 'languages': '[]', 'topics': '[]', 'edited_fields': '[]'},
        {'id': 12, 'title': 'Pending', 'languages': '[]', 'topics': '[]', 'edited_fields': '[]'},
    ]
    approved = [{
        'project_id': 11, 'summary': 'An approved summary.', 'description': 'Approved description.',
        'case_study_problem': 'Problem.', 'case_study_built': 'Built.', 'case_study_result': 'Result.',
    }]

    class Cursor:
        rows: ClassVar[list] = []

        def execute(self, sql, params=None):
            self.rows = projects if sql.startswith('SELECT * FROM projects') else approved
            if 'project_ai_drafts' in sql:
                assert params == ('approved',)

        def fetchall(self):
            return self.rows

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def close(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())

    loaded = app_module.get_projects()

    assert loaded[0]['ai_summary'] == 'An approved summary.'
    assert loaded[0]['ai_case_study_result'] == 'Result.'
    assert loaded[1]['ai_summary'] == ''


def test_ai_draft_save_and_approval_flow(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    saved = []
    current_status = {'value': 'pending'}

    class Cursor:
        def execute(self, sql, params=None):
            if sql.startswith('UPDATE project_ai_drafts'):
                saved.append(params)
                current_status['value'] = params[5]

        def fetchone(self):
            return {'status': current_status['value']}

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())
    fields = {
        'summary': 'Edited summary', 'description': 'Edited description.',
        'case_study_problem': 'Problem', 'case_study_built': 'What I built', 'case_study_result': 'Result',
    }

    saved_response = client.post('/admin/ai-drafts/11', data={**fields, 'action': 'save'})
    approved_response = client.post('/admin/ai-drafts/11', data={**fields, 'action': 'approve'})
    revised_response = client.post('/admin/ai-drafts/11', data={**fields, 'summary': 'Revised', 'action': 'save'})

    assert saved_response.status_code == approved_response.status_code == revised_response.status_code == 302
    assert saved[0][5] == 'pending'
    assert saved[1][5] == 'approved'
    assert saved[2][5] == 'pending'


def test_admin_ai_drafts_page_lists_pending_drafts(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    draft = {
        'project_id': 11, 'project_title': 'Readme project', 'github_full_name': 'owner/repo',
        'summary': 'Pending summary', 'description': 'Pending description.',
        'case_study_problem': 'Problem', 'case_study_built': 'Built', 'case_study_result': 'Unknown',
        'status': 'pending', 'readme_hash': 'abc',
    }

    class Cursor:
        def execute(self, sql, params=None):
            pass

        def fetchall(self):
            return [draft]

        def close(self):
            pass

    class Connection:
        def cursor(self, cursor_factory=None):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: Connection())

    response = client.get('/admin/ai-drafts')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Readme project' in page
    assert 'Approve and publish' in page
    assert 'Pending summary' in page


def test_github_client_decodes_raw_readme_for_ai_processing(monkeypatch):
    readme = '# Facts from the README'
    encoded = base64.b64encode(readme.encode('utf-8')).decode('ascii')
    client = GitHubClient('owner')
    monkeypatch.setattr(client, '_get_json', lambda url, allow_missing=False: {
        'encoding': 'base64', 'content': encoded,
    })

    assert client.get_repository_readme('owner/repo') == readme


def test_ai_summaries_skip_unchanged_readmes(monkeypatch):
    project = {'id': 21, 'github_full_name': 'owner/repo'}
    readme = '# Documented facts'
    readme_hash = app_module._readme_hash(readme)
    current_hash = {'value': None}
    generated = []
    saved = []

    class Github:
        def get_repository_readme(self, full_name):
            return readme

    class FakeGroq:
        def __init__(self, api_key, model):
            pass

        def generate(self, contents, before_request):
            generated.append(contents)
            return {
                'summary': 'Summary', 'description': 'Two sentences. Another sentence.',
                'case_study': {'problem': 'unknown', 'what_i_built': 'unknown', 'result': 'unknown'},
            }

    def save(project_id, content_hash, draft):
        saved.append((project_id, content_hash, draft))
        current_hash['value'] = content_hash

    monkeypatch.setitem(app_module.app.config, 'GROQ_API_KEY', 'test-key')
    monkeypatch.setattr(app_module, '_github_ai_projects', lambda: [project])
    monkeypatch.setattr(app_module, '_github_client', lambda: Github())
    monkeypatch.setattr(app_module, '_existing_ai_readme_hash', lambda project_id: current_hash['value'])
    monkeypatch.setattr(app_module, '_save_ai_draft', save)
    monkeypatch.setattr(app_module, 'GroqClient', FakeGroq)

    first = app_module.generate_ai_summaries()
    second = app_module.generate_ai_summaries()

    assert first['generated'] == 1
    assert second['unchanged'] == 1
    assert generated == [readme]
    assert saved[0][1] == readme_hash


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


def test_refresh_description_generates_readme_ai_draft(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setitem(app.config, 'GROQ_API_KEY', 'groq-test-key')
    saved = []

    class FakeCursor:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return {'github_full_name': 'example/project'}

        def close(self):
            pass

    class FakeConnection:
        def cursor(self, cursor_factory=None):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    class FakeClient:
        def get_repository_readme(self, full_name):
            assert full_name == 'example/project'
            return '# Project\nA factual README.'

    class FakeGroqClient:
        def __init__(self, api_key, model):
            assert api_key == 'groq-test-key'

        def generate(self, readme, before_request=None):
            assert readme == '# Project\nA factual README.'
            assert before_request is app_module._claim_groq_api_request
            return {'summary': 'Short summary.', 'description': 'AI rewrite.', 'case_study': {}}

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConnection())
    monkeypatch.setattr(app_module, '_github_client', lambda: FakeClient())
    monkeypatch.setattr(app_module, 'GroqClient', FakeGroqClient)
    monkeypatch.setattr(app_module, '_claim_groq_api_request', lambda: True)
    monkeypatch.setattr(app_module, '_save_ai_draft', lambda project_id, readme_hash, draft: saved.append((project_id, readme_hash, draft)))

    response = client.post('/admin/projects/42/refresh-description')

    assert response.status_code == 302
    assert response.location.endswith('/admin/ai-drafts')
    assert saved[0][0] == 42
    assert saved[0][2]['description'] == 'AI rewrite.'


def test_refresh_description_warns_when_github_has_no_readme(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)
    monkeypatch.setitem(app.config, 'GROQ_API_KEY', 'groq-test-key')
    statements = []

    class FakeCursor:
        def execute(self, sql, params=None):
            statements.append((sql, params))

        def fetchone(self):
            return {'github_full_name': 'example/project'}

        def close(self):
            pass

    class FakeConnection:
        def cursor(self, cursor_factory=None):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    class FakeClient:
        def get_repository_readme(self, full_name):
            return ''

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConnection())
    monkeypatch.setattr(app_module, '_github_client', lambda: FakeClient())

    response = client.post('/admin/projects/42/refresh-description')

    assert response.status_code == 302
    assert not any(sql.startswith('UPDATE projects') for sql, _ in statements)


def test_github_failure_is_reported_and_public_page_uses_saved_data(client, monkeypatch):
    authenticate_test_user(client, monkeypatch)

    class FailedClient:
        def list_repositories(self, enrich=True):
            raise GitHubAPIError('GitHub could not be reached. Your saved projects are unchanged.')

    monkeypatch.setattr(app_module, '_github_client', lambda: FailedClient())
    response = client.get('/admin/github/import')
    assert response.status_code == 200
    assert b'GitHub could not be reached' in response.data

    monkeypatch.setattr(app_module, 'get_projects', list)
    monkeypatch.setattr(app_module, 'get_content_from_db', dict)
    monkeypatch.setattr(app_module, 'get_skills_from_table', dict)
    assert client.get('/').status_code == 200


def test_github_client_wraps_network_failures(monkeypatch):
    import requests

    def raise_timeout(*args, **kwargs):
        raise requests.Timeout('request timed out')

    monkeypatch.setattr('github_client.request_with_retries', raise_timeout)
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