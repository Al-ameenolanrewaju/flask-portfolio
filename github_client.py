import base64
import re

import requests


class GitHubAPIError(Exception):
    pass


class GitHubClient:
    API_ROOT = 'https://api.github.com'
    CACHE_SECONDS = 600

    def __init__(self, username, token=None, cache=None):
        self.username = username
        self.token = token
        self.cache = cache

    def _get_json(self, url, allow_missing=False):
        cache_key = f'github-api:{url}'
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                if cached == {'__github_not_found__': True}:
                    return None
                return cached

        headers = {'Accept': 'application/vnd.github+json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        try:
            response = requests.get(url, headers=headers, timeout=(3.05, 10))
        except requests.RequestException as error:
            raise GitHubAPIError('GitHub could not be reached. Your saved projects are unchanged.') from error

        if allow_missing and response.status_code == 404:
            if self.cache:
                self.cache.set(cache_key, {'__github_not_found__': True}, timeout=self.CACHE_SECONDS)
            return None
        if response.status_code in (403, 429) or response.headers.get('X-RateLimit-Remaining') == '0':
            reset = response.headers.get('X-RateLimit-Reset')
            detail = f' Try again after {reset}.' if reset else ' Try again later or configure GITHUB_TOKEN.'
            raise GitHubAPIError(f'GitHub API rate limit reached.{detail}')
        try:
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise GitHubAPIError('GitHub returned an invalid response. Your saved projects are unchanged.') from error

        if self.cache:
            self.cache.set(cache_key, data, timeout=self.CACHE_SECONDS)
        return data

    @staticmethod
    def _readme_paragraph(markdown):
        markdown = re.sub(r'```.*?```', '', markdown, flags=re.DOTALL)
        for paragraph in re.split(r'\n\s*\n', markdown):
            text = paragraph.strip()
            if not text or text.startswith('#') or text.startswith('!['):
                continue
            text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
            text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
            text = re.sub(r'[`*_~>#]', '', text).strip()
            if text:
                return text
        return ''

    def list_repositories(self, enrich=True):
        if not self.username:
            raise GitHubAPIError('Set GITHUB_USERNAME before importing projects.')

        repositories = []
        page = 1
        while True:
            page_repositories = self._get_json(
                f'{self.API_ROOT}/users/{self.username}/repos?type=owner&sort=pushed&per_page=100&page={page}'
            )
            if not page_repositories:
                break
            repositories.extend(page_repositories)
            if len(page_repositories) < 100:
                break
            page += 1

        return self.enrich_repositories(repositories) if enrich else repositories

    def enrich_repositories(self, repositories):
        for repository in repositories:
            full_name = repository['full_name']
            repository['languages'] = self._get_json(f'{self.API_ROOT}/repos/{full_name}/languages')
            topic_data = self._get_json(f'{self.API_ROOT}/repos/{full_name}/topics')
            repository['topics'] = topic_data.get('names', [])
            if not repository.get('description'):
                readme = self._get_json(f'{self.API_ROOT}/repos/{full_name}/readme', allow_missing=True)
                if readme and readme.get('content'):
                    try:
                        markdown = base64.b64decode(readme['content']).decode('utf-8', errors='replace')
                        repository['description'] = self._readme_paragraph(markdown)
                    except (ValueError, KeyError):
                        repository['description'] = ''
                else:
                    repository['description'] = ''
            repository['preview_image'] = f"https://opengraph.githubassets.com/{repository['id']}/{full_name}"
        return repositories