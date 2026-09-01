import pytest
import app as app_module
from app import app
from config import TestingConfig
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
        user = User(username='admin', email='admin@example.com', password='pw')
        db.session.add(user)
        db.session.commit()

    with client.session_transaction() as session:
        session['_user_id'] = '1'
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