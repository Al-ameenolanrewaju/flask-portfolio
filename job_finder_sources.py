from copy import deepcopy
from datetime import datetime, timezone
from html import unescape
import re
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import requests

from external_http import request_with_retries


CACHE_SECONDS = 6 * 60 * 60
REQUEST_TIMEOUT = (3.05, 15)
USER_AGENT = 'AlameenPortfolioJobFinder/1.0'


class JobSourceError(Exception):
    pass


class JobSource:
    key = ''
    name = ''
    source_url = ''

    def __init__(self):
        self._cached_jobs = None
        self._cached_at = 0.0

    def fetch(self):
        if self._cached_jobs is not None and time.monotonic() - self._cached_at < CACHE_SECONDS:
            return deepcopy(self._cached_jobs)
        jobs = self._fetch()
        self._cached_jobs = jobs
        self._cached_at = time.monotonic()
        return deepcopy(jobs)

    def has_fresh_cache(self):
        return self._cached_jobs is not None and time.monotonic() - self._cached_at < CACHE_SECONDS

    def _fetch(self):
        raise NotImplementedError

    def _get_json(self, url, params=None):
        try:
            response = request_with_retries(
                'GET', url,
                params=params,
                headers={'Accept': 'application/json', 'User-Agent': USER_AGENT},
                timeout=REQUEST_TIMEOUT,
                attempts=3,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            raise JobSourceError(f'{self.name} feed request failed') from error


def canonical_job_url(url):
    if not url:
        return ''
    try:
        parsed = urlsplit(str(url).strip())
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return ''
        host = parsed.hostname.casefold()
        if parsed.port:
            host = f'{host}:{parsed.port}'
        path = parsed.path.rstrip('/') or '/'
        return urlunsplit((parsed.scheme.lower(), host, path, '', ''))
    except (TypeError, ValueError):
        return ''


def safe_job_url(url):
    try:
        parsed = urlsplit(str(url or '').strip())
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return ''
        return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or '/', parsed.query, ''))
    except (TypeError, ValueError):
        return ''


def normalize_key(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def extract_mailto(description):
    text = unescape(str(description or ''))
    match = re.search(r'href\s*=\s*["\']mailto:([^"\'?>\s]+)', text, re.IGNORECASE)
    if not match:
        return None
    address = match.group(1).split('?', 1)[0].strip()
    return address if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', address) else None


def parse_posted_at(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def normalize_job(source, raw):
    title = str(raw.get('title') or raw.get('position') or '').strip()
    if not title:
        return None
    original_url = safe_job_url(raw.get('url') or raw.get('job_url'))
    if not original_url:
        return None
    description = str(raw.get('description') or '')
    company = str(raw.get('company_name') or raw.get('company') or '').strip()
    posting_url_key = canonical_job_url(original_url)
    apply_url = safe_job_url(raw.get('apply_url') or original_url) or original_url
    external_id = raw.get('id') or raw.get('slug')
    application_email = raw.get('application_email') or raw.get('email') or extract_mailto(description)
    if application_email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', str(application_email).strip()):
        application_email = None
    return {
        'source_key': source.key,
        'source_name': source.name,
        'source_url': source.source_url,
        'external_id': str(external_id) if external_id is not None else None,
        'posting_url': original_url,
        'posting_url_key': posting_url_key,
        'apply_url': apply_url,
        'application_email': str(application_email).strip() if application_email else None,
        'title': title[:500],
        'title_key': normalize_key(title)[:500],
        'company': company[:300],
        'company_key': normalize_key(company)[:300],
        'location': str(raw.get('candidate_required_location') or raw.get('location') or raw.get('region') or '').strip()[:500],
        'job_type': str(raw.get('job_type') or raw.get('type') or '').strip()[:100],
        'posted_at': parse_posted_at(raw.get('publication_date') or raw.get('date') or raw.get('epoch')),
        'description': description,
        'keywords': [str(tag).strip() for tag in (raw.get('tags') or []) if str(tag).strip()],
    }


def deduplicate_jobs(jobs):
    unique = []
    seen_urls = set()
    seen_company_titles = set()
    for job in jobs:
        url_key = job.get('posting_url_key') or canonical_job_url(job.get('posting_url'))
        company_key = job.get('company_key') or normalize_key(job.get('company'))
        title_key = job.get('title_key') or normalize_key(job.get('title'))
        company_title = (company_key, title_key) if company_key and title_key else None
        if not url_key or url_key in seen_urls or (company_title and company_title in seen_company_titles):
            continue
        seen_urls.add(url_key)
        if company_title:
            seen_company_titles.add(company_title)
        unique.append(job)
    return unique


class RemotiveSource(JobSource):
    key = 'remotive'
    name = 'Remotive'
    source_url = 'https://remotive.com/remote-jobs/api'
    endpoint = 'https://remotive.com/api/remote-jobs'

    def _fetch(self):
        payload = self._get_json(self.endpoint, {'category': 'software-dev', 'limit': 100})
        records = payload.get('jobs', []) if isinstance(payload, dict) else []
        return [job for raw in records if (job := normalize_job(self, raw))]


class RemoteOKSource(JobSource):
    key = 'remoteok'
    name = 'RemoteOK'
    source_url = 'https://remoteok.com/api'
    endpoint = 'https://remoteok.com/api'

    def _fetch(self):
        payload = self._get_json(self.endpoint)
        if not isinstance(payload, list):
            raise JobSourceError('RemoteOK returned an unexpected response')
        records = [item for item in payload if isinstance(item, dict) and (item.get('position') or item.get('title'))]
        return [job for raw in records if (job := normalize_job(self, raw))]


SOURCE_REGISTRY = {
    RemotiveSource.key: RemotiveSource,
    RemoteOKSource.key: RemoteOKSource,
}
