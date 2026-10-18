from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
import pytest

import screenshot_provider


def test_screenshotone_provider_requests_webp_with_bounded_dimensions(monkeypatch):
    response = SimpleNamespace(status_code=200, content=b'webp-bytes', raise_for_status=Mock())
    request = Mock(return_value=response)
    monkeypatch.setattr(screenshot_provider, 'request_with_retries', request)

    result = screenshot_provider.ScreenshotOneProvider('test-key').capture('https://demo.example')

    assert result == b'webp-bytes'
    request.assert_called_once()
    args, kwargs = request.call_args
    assert args[:2] == ('GET', screenshot_provider.ScreenshotOneProvider.ENDPOINT)
    assert kwargs['headers'] == {'X-Access-Key': 'test-key'}
    assert kwargs['params']['format'] == 'webp'
    assert kwargs['params']['viewport_width'] == 1280
    assert kwargs['params']['viewport_height'] == 720
    assert kwargs['timeout'] == (3.05, 35)


def test_screenshotone_quota_error_is_distinguished(monkeypatch):
    response = SimpleNamespace(
        status_code=400,
        json=lambda: {'error': {'code': 'screenshots_limit_reached', 'message': 'limit'}},
    )
    monkeypatch.setattr(screenshot_provider, 'request_with_retries', lambda *args, **kwargs: response)

    with pytest.raises(screenshot_provider.ScreenshotQuotaExceeded):
        screenshot_provider.ScreenshotOneProvider('test-key').capture('https://demo.example')


def test_fallback_card_and_normalized_image_have_webp_dimensions():
    card = screenshot_provider.create_fallback_card('Portfolio project', 'https://demo.example', ['Python', 'Flask'])
    with Image.open(BytesIO(card)) as image:
        assert image.format == 'WEBP'
        assert image.size == (1280, 720)

    source = Image.new('RGB', (640, 480), color='white')
    source_data = BytesIO()
    source.save(source_data, format='PNG')
    normalized = screenshot_provider.normalize_webp(source_data.getvalue())
    with Image.open(BytesIO(normalized)) as image:
        assert image.format == 'WEBP'
        assert image.size == (1280, 720)