import pytest

import app as app_module
from app import app
from config import TestingConfig
from whatsapp import CallMeBotProvider


@pytest.fixture
def client(monkeypatch, request):
    app.config.from_object(TestingConfig)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', False)
    with app.test_client() as test_client:
        test_client.environ_base['REMOTE_ADDR'] = f"192.0.2.{abs(hash(request.node.nodeid)) % 254 + 1}"
        yield test_client


def test_callmebot_provider_uses_configured_recipient_and_retries(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response()

    monkeypatch.setattr('whatsapp.request_with_retries', fake_request)
    provider = CallMeBotProvider('+2348000000000', 'callmebot-key')

    assert provider.send_message('New contact')
    assert calls == [(
        'GET',
        CallMeBotProvider.ENDPOINT,
        {
            'params': {'phone': '+2348000000000', 'text': 'New contact', 'apikey': 'callmebot-key'},
            'timeout': (3.05, 10),
        },
    )]


def test_contact_is_saved_before_notification_and_triage_are_queued(client, monkeypatch):
    statements = []

    class FakeCursor:
        def execute(self, sql, params=None):
            statements.append(sql)

        def fetchone(self):
            return (42,)

        def close(self):
            pass

    class FakeConnection:
        committed = False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            pass

    connection = FakeConnection()
    queued = []

    class FakeExecutor:
        def submit(self, function, *args):
            assert connection.committed
            queued.append((function, args))

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: connection)
    monkeypatch.setattr(app_module, 'send_resend_contact_notification', lambda *args: True)
    monkeypatch.setattr(app_module, 'contact_alert_executor', FakeExecutor())
    monkeypatch.setitem(app.config, 'CALLMEBOT_PHONE', 'phone')
    monkeypatch.setitem(app.config, 'CALLMEBOT_API_KEY', 'key')

    response = client.post('/contact', data={
        'name': 'Sender',
        'email': 'sender@example.com',
        'subject': 'Hello',
        'message': 'A message',
    })

    assert response.status_code == 302
    assert connection.committed
    assert any('message, created_at' in sql and 'NOW()' in sql for sql in statements)
    assert len(queued) == 2
    assert queued[0][0] is app_module.send_contact_alerts
    assert queued[1][0] is app_module.triage_contact_message


def test_explicit_contact_draft_send_uses_resend_and_escapes_html(monkeypatch):
    captured = []
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'resend-key')
    monkeypatch.setitem(app.config, 'RESEND_FROM', 'Portfolio <hello@example.com>')
    monkeypatch.setattr(app_module.resend.Emails, 'send', lambda payload: captured.append(payload))

    with app.app_context():
        assert app_module.send_resend_contact_draft({
            'email': 'sender@example.com', 'subject': 'Question',
            'reply_draft': '<script>draft</script>',
        })

    payload = captured[0]
    assert payload['to'] == ['sender@example.com']
    assert payload['subject'] == 'Re: Question'
    assert '&lt;script&gt;draft&lt;/script&gt;' in payload['html']


def test_contact_notification_uses_configured_sender_recipient_and_reply_to(monkeypatch):
    captured = []
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'resend-key')
    monkeypatch.setitem(app.config, 'RESEND_FROM', 'onboarding@resend.dev')
    monkeypatch.setitem(app.config, 'CONTACT_EMAIL', 'owner@example.com')
    monkeypatch.setattr(app_module.resend.Emails, 'send', lambda payload: captured.append(payload))

    with app.app_context():
        assert app_module.send_resend_contact_notification(
            'Visitor', 'visitor@example.com', 'Project inquiry', 'Could we talk?', 'https://portfolio.example'
        )

    payload = captured[0]
    assert payload['from'] == 'onboarding@resend.dev'
    assert payload['to'] == ['owner@example.com']
    assert payload['reply_to'] == 'visitor@example.com'
    assert 'mailto:visitor@example.com' in payload['html']
    assert 'Could we talk?' in payload['html']


def test_contact_rejects_invalid_email_and_missing_subject(client, monkeypatch):
    monkeypatch.setattr(
        app_module, 'get_db_connection',
        lambda: pytest.fail('invalid contact data must not be saved'),
    )
    monkeypatch.setattr(
        app_module, 'send_resend_contact_notification',
        lambda *args: pytest.fail('invalid contact data must not be emailed'),
    )

    response = client.post('/contact', data={
        'name': 'Visitor',
        'email': 'not-an-email',
        'subject': '',
        'message': 'Hello',
    })

    assert response.status_code == 302
    with client.session_transaction() as session:
        category, message = session['_flashes'][-1]
    assert category == 'danger'
    assert 'valid email address' in message


def test_contact_email_alerts_are_sent_for_all_priorities_and_whatsapp_only_for_high(monkeypatch):
    alerts = []
    monkeypatch.setattr(app_module, 'send_resend_contact_notification', lambda *args: alerts.append('email'))

    class Provider:
        def send_message(self, text):
            alerts.append('whatsapp')

    monkeypatch.setattr(app_module, '_whatsapp_provider', lambda: Provider())

    assert app_module.send_contact_alerts(
        'Visitor', 'visitor@example.com', 'Question', 'Message', 'https://site.test',
    ) is True
    assert alerts == ['email']
    assert app_module.send_contact_alerts(
        'Visitor', 'visitor@example.com', 'Question', 'Message', 'https://site.test', priority='high',
    ) is True
    assert alerts == ['email', 'email', 'whatsapp']


def test_triage_worker_sends_high_priority_alert_without_duplicate_email_or_reply(monkeypatch):
    alerts = []
    monkeypatch.setattr(app_module.contact_triage_service, 'triage', lambda message_id: {
        'saved': True,
        'priority': 'high',
        'reply_draft': 'A draft for explicit approval.',
        'message': {
            'name': 'Visitor', 'email': 'visitor@example.com', 'subject': 'Question', 'message': 'Hello',
        },
    })
    monkeypatch.setattr(app_module, 'send_contact_alerts', lambda *args, **kwargs: alerts.append(kwargs))
    monkeypatch.setattr(
        app_module, 'send_resend_contact_draft',
        lambda *args: pytest.fail('triage must never send the generated reply'),
    )

    result = app_module.triage_contact_message(42, 'https://portfolio.example')

    assert result['saved'] is True
    assert alerts == [{'priority': 'high', 'send_email': False}]


def test_contact_reply_requires_a_separate_send_confirmation(client, monkeypatch):
    from models import User

    user = User(id=99125, username='contact-admin', email='contact-admin@example.com', password='unused')
    monkeypatch.setattr(app_module.login_manager, '_user_callback', lambda user_id: user)
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True

    class Service:
        def claim_send(self, message_id):
            pytest.fail('missing send confirmation must not claim or send the draft')

    monkeypatch.setitem(app.extensions, 'contact_triage_service', Service())
    monkeypatch.setattr(
        app_module, 'send_resend_contact_draft',
        lambda *args: pytest.fail('missing send confirmation must not call Resend'),
    )

    response = client.post('/admin/contact-messages/42/send', data={})

    assert response.status_code == 400
