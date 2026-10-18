import pytest

import app as app_module
from app import app
from config import TestingConfig
from whatsapp import CallMeBotProvider


@pytest.fixture
def client(monkeypatch):
    app.config.from_object(TestingConfig)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', False)
    with app.test_client() as test_client:
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

    assert len(calls) == 3


def test_sender_autoreply_uses_resend_and_escapes_name(monkeypatch):
    captured = []
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'resend-key')
    monkeypatch.setitem(app.config, 'RESEND_FROM', 'Portfolio <hello@example.com>')
    monkeypatch.setattr(app_module, 'request_with_retries', lambda *args, **kwargs: captured.append((args, kwargs)) or type('Response', (), {'raise_for_status': lambda self: None})())

    with app.app_context():
        assert app_module.send_resend_contact_reply('<Sender>', 'sender@example.com')

    payload = captured[0][1]['json']
    assert payload['to'] == ['sender@example.com']
    assert 'Thanks for reaching out' in payload['subject']
    assert '&lt;Sender&gt;' in payload['html']
