import pytest
from app import app
from config import TestingConfig





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