from types import SimpleNamespace
from unittest.mock import Mock

import link_checker


def test_check_link_follows_relative_redirects_and_closes_responses(monkeypatch):
    redirect = SimpleNamespace(status_code=302, headers={'Location': '/ready'}, close=Mock())
    success = SimpleNamespace(status_code=200, headers={}, close=Mock())
    requested = []
    responses = iter([redirect, success])

    def request(method, url, **kwargs):
        requested.append((method, url, kwargs))
        return next(responses)

    monkeypatch.setattr(link_checker, 'request_with_retries', request)

    assert link_checker.check_link('https://example.com/start') == 'ok'
    assert [entry[1] for entry in requested] == [
        'https://example.com/start', 'https://example.com/ready',
    ]
    redirect.close.assert_called_once()
    success.close.assert_called_once()
    assert requested[0][2]['timeout'] == (3.05, 8)


def test_check_link_rejects_redirect_loops_and_private_targets(monkeypatch):
    redirect = SimpleNamespace(status_code=301, headers={'Location': '/start'}, close=Mock())
    request = Mock(return_value=redirect)
    monkeypatch.setattr(link_checker, 'request_with_retries', request)

    assert link_checker.check_link('https://example.com/start') == 'broken'
    request.assert_called_once()
    assert link_checker.check_link('http://127.0.0.1/admin') == 'broken'