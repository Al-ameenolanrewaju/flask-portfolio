import time

import requests


def request_with_retries(method, url, *, timeout=(3.05, 10), attempts=3, **kwargs):
    last_response = None
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.request(method, url, timeout=timeout, **kwargs)
            last_response = response
            if response.status_code != 429 and response.status_code < 500:
                return response
        except requests.RequestException as error:
            last_error = error

        if attempt + 1 < attempts:
            retry_after = None
            if last_response is not None:
                try:
                    retry_after = float(last_response.headers.get('Retry-After', ''))
                except (TypeError, ValueError):
                    retry_after = None
            delay = min(retry_after, 5) if retry_after is not None and retry_after >= 0 else 0.5 * (2 ** attempt)
            time.sleep(delay)

    if last_response is not None:
        return last_response
    raise last_error