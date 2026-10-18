import ipaddress
from urllib.parse import urljoin, urlparse

import requests

from external_http import request_with_retries


MAX_REDIRECTS = 8


def _is_public_http_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return False
        hostname = parsed.hostname.casefold()
        if hostname == 'localhost' or hostname.endswith('.localhost'):
            return False
        try:
            return ipaddress.ip_address(hostname).is_global
        except ValueError:
            return True
    except (TypeError, ValueError):
        return False


def check_link(url):
    current_url = (url or '').strip()
    visited = set()
    for redirect_number in range(MAX_REDIRECTS + 1):
        if not _is_public_http_url(current_url) or current_url in visited:
            return 'broken'
        visited.add(current_url)
        response = None
        try:
            response = request_with_retries(
                'GET', current_url, timeout=(3.05, 8), allow_redirects=False,
                stream=True, headers={'User-Agent': 'PortfolioLinkChecker/1.0'},
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get('Location')
                if not location or redirect_number == MAX_REDIRECTS:
                    return 'broken'
                current_url = urljoin(current_url, location)
                continue
            return 'ok' if 200 <= response.status_code < 400 else 'broken'
        except requests.RequestException:
            return 'broken'
        finally:
            if response is not None:
                response.close()
    return 'broken'