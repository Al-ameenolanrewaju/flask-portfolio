import unicodedata
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from external_http import request_with_retries

IMAGE_SIZE = (1280, 720)


class ScreenshotError(Exception):
    pass


class ScreenshotQuotaExceeded(ScreenshotError):
    pass


class ScreenshotOneProvider:
    ENDPOINT = 'https://api.screenshotone.com/take'

    def __init__(self, access_key):
        self.access_key = access_key

    def capture(self, url):
        response = request_with_retries(
            'GET',
            self.ENDPOINT,
            headers={'X-Access-Key': self.access_key},
            params={
                'url': url,
                'format': 'webp',
                'viewport_width': IMAGE_SIZE[0],
                'viewport_height': IMAGE_SIZE[1],
                'image_width': IMAGE_SIZE[0],
                'image_height': IMAGE_SIZE[1],
                'cache': 'true',
                'cache_ttl': 604800,
                'timeout': 25,
                'navigation_timeout': 20,
            },
            timeout=(3.05, 35),
        )
        if response.status_code == 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = payload.get('error', payload)
            error_code = error.get('code') or payload.get('error_code')
            if error_code == 'screenshots_limit_reached':
                raise ScreenshotQuotaExceeded('ScreenshotOne monthly quota was reached')
            raise ScreenshotError(error.get('message') or 'ScreenshotOne rejected the request')
        try:
            response.raise_for_status()
            if not response.content:
                raise ScreenshotError('ScreenshotOne returned an empty image')
            return response.content
        except requests.RequestException as error:
            raise ScreenshotError('ScreenshotOne request failed') from error


def normalize_webp(image_data):
    try:
        with Image.open(BytesIO(image_data)) as source:
            image = ImageOps.fit(source.convert('RGB'), IMAGE_SIZE, method=Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format='WEBP', quality=82, method=4)
            return output.getvalue()
    except (OSError, ValueError) as error:
        raise ScreenshotError('Screenshot response was not a valid image') from error


def _plain_text(value):
    return unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode('ascii')


def _wrap_text(draw, text, font, max_width):
    lines = []
    current = ''
    for word in _plain_text(text).split():
        candidate = f'{current} {word}'.strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def create_fallback_card(title, url, technologies=()):
    image = Image.new('RGB', IMAGE_SIZE)
    draw = ImageDraw.Draw(image)
    for y in range(IMAGE_SIZE[1]):
        progress = y / IMAGE_SIZE[1]
        color = (16 + int(15 * progress), 34 + int(20 * progress), 29 + int(15 * progress))
        draw.line((0, y, IMAGE_SIZE[0], y), fill=color)

    draw.rounded_rectangle((864, 108, 1170, 414), radius=34, outline=(214, 111, 72), width=3)
    draw.line((914, 464, 1120, 258), fill=(220, 164, 93), width=4)
    label_font = ImageFont.load_default(size=22)
    title_font = ImageFont.load_default(size=58)
    body_font = ImageFont.load_default(size=22)
    draw.text((92, 88), 'PROJECT / PORTFOLIO', font=label_font, fill=(231, 175, 105))

    title_lines = _wrap_text(draw, title or 'Untitled project', title_font, 790)[:3]
    y = 220
    for line in title_lines:
        draw.text((92, y), line, font=title_font, fill=(244, 244, 229))
        y += 76
    draw.text((92, 490), _plain_text(url)[:70], font=body_font, fill=(180, 200, 187))
    tag_text = '  /  '.join(_plain_text(value) for value in technologies[:5])
    if tag_text:
        draw.text((92, 566), tag_text[:95], font=body_font, fill=(231, 175, 105))

    output = BytesIO()
    image.save(output, format='WEBP', quality=82, method=4)
    return output.getvalue()