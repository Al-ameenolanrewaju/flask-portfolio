import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import groq_client


def _success_response():
    draft = {
        'summary': 'A concise project summary.',
        'description': 'This project provides a documented feature. The README describes its interface.',
        'case_study': {'problem': 'unknown', 'what_i_built': 'A documented tool.', 'result': 'unknown'},
    }
    return SimpleNamespace(
        status_code=200,
        headers={},
        json=lambda: {'choices': [{'message': {'content': json.dumps(draft)}}]},
        raise_for_status=Mock(),
    )


def test_groq_uses_configured_model_and_readme_only_factual_prompt(monkeypatch):
    response = _success_response()
    request = Mock(return_value=response)
    monkeypatch.setattr(groq_client, 'request_with_retries', request)

    draft = groq_client.GroqClient('test-key', 'configured-model').generate('README facts only')

    assert draft['summary'] == 'A concise project summary.'
    args, kwargs = request.call_args
    assert args[:2] == ('POST', groq_client.GroqClient.ENDPOINT)
    assert kwargs['json']['model'] == 'configured-model'
    prompt = kwargs['json']['messages'][1]['content']
    assert 'Do not infer, assume, or invent facts' in prompt
    assert 'unknown' in prompt
    assert '<README>\nREADME facts only\n</README>' in prompt


def test_groq_retries_rate_limits_and_consumes_one_budget_per_attempt(monkeypatch):
    rate_limited = SimpleNamespace(status_code=429, headers={'Retry-After': '0'})
    request = Mock(side_effect=[rate_limited, _success_response()])
    budget = Mock(return_value=True)
    monkeypatch.setattr(groq_client, 'request_with_retries', request)
    monkeypatch.setattr(groq_client.time, 'sleep', Mock())

    groq_client.GroqClient('test-key', 'model').generate('README', before_request=budget)

    assert request.call_count == 2
    assert budget.call_count == 2


def test_groq_daily_cap_prevents_external_request(monkeypatch):
    request = Mock()
    monkeypatch.setattr(groq_client, 'request_with_retries', request)

    with pytest.raises(groq_client.GroqDailyCapReached):
        groq_client.GroqClient('test-key', 'model').generate('README', before_request=lambda: False)
    request.assert_not_called()
