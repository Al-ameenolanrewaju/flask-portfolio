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


def test_contact_is_saved_before_background_alerts_and_alert_failures_are_isolated(client, monkeypatch):
    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

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
    assert len(queued) == 1

    calls = []

    def failed_alert(*args, **kwargs):
        calls.append(args)
        raise RuntimeError('provider unavailable')

    class FailedWhatsAppProvider:
        def send_message(self, message):
            calls.append(message)
            raise RuntimeError('CallMeBot unavailable')

    monkeypatch.setattr(app_module, 'send_resend_contact_notification', failed_alert)
    monkeypatch.setattr(app_module, 'send_resend_contact_reply', failed_alert)
    monkeypatch.setattr(app_module, '_whatsapp_provider', lambda: FailedWhatsAppProvider())
    queued[0][0](*queued[0][1])

    assert len(calls) == 2


def test_sender_autoreply_uses_resend_and_escapes_name(monkeypatch):
    captured = []
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'resend-key')
    monkeypatch.setitem(app.config, 'RESEND_FROM', 'Portfolio <hello@example.com>')
    monkeypatch.setattr(app_module.resend.Emails, 'send', lambda payload: captured.append(payload))

    with app.app_context():
        assert app_module.send_resend_contact_reply('<Sender>', 'sender@example.com')

    payload = captured[0]
    assert payload['to'] == ['sender@example.com']
    assert 'Thanks for reaching out' in payload['subject']
    assert '&lt;Sender&gt;' in payload['html']


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


def test_contact_email_failure_is_friendly_and_does_not_log_secrets(client, monkeypatch, caplog):
    class FakeCursor:
        def execute(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(app_module, 'get_db_connection', lambda: FakeConnection())
    monkeypatch.setattr(
        app_module, 'send_resend_contact_notification',
        lambda *args: (_ for _ in ()).throw(RuntimeError('re_super-secret-key')),
    )

    response = client.post('/contact', data={
        'name': 'Visitor',
        'email': 'visitor@example.com',
        'subject': 'Question',
        'message': 'Hello',
    })

    assert response.status_code == 302
    with client.session_transaction() as session:
        category, message = session['_flashes'][-1]
    assert category == 'danger'
    assert 'try again shortly' in message
    assert 're_super-secret-key' not in caplog.text
