import json
import logging
import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from config import Config
from job_finder_sources import SOURCE_REGISTRY, deduplicate_jobs


logger = logging.getLogger(__name__)

DEFAULT_PREFERENCES = {
    'target_titles': [
        'Python Developer', 'Flask Developer', 'Backend Developer',
        'Backend Engineer', 'Junior Backend Developer',
    ],
    'keywords': ['Python', 'Flask', 'Django', 'FastAPI', 'backend', 'PostgreSQL'],
    'excluded_keywords': ['senior', 'staff', 'principal', 'lead', 'manager', 'director'],
    'locations': ['Worldwide', 'Lagos, Nigeria'],
    'remote_only': True,
    'minimum_match_score': 65,
    'excluded_companies': [],
    'daily_send_cap': 5,
    'enabled_sources': ['remotive', 'remoteok'],
}

PREFERENCE_FIELDS = tuple(DEFAULT_PREFERENCES)


def _database_url():
    try:
        from flask import current_app
        value = current_app.config.get('SQLALCHEMY_DATABASE_URI')
    except RuntimeError:
        value = Config.SQLALCHEMY_DATABASE_URI
    value = value or os.environ.get('DATABASE_URL', '')
    if value.startswith('postgres://'):
        value = value.replace('postgres://', 'postgresql://', 1)
    return value


def connect_database():
    return psycopg2.connect(_database_url())


def _list_value(value, field, limit=40):
    if isinstance(value, str):
        values = re_split_lines(value)
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = []
    cleaned = []
    seen = set()
    for item in values:
        text = ' '.join(str(item).split())[:160]
        key = text.casefold()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
        if len(cleaned) >= limit:
            break
    if field in {'target_titles', 'keywords', 'locations'} and not cleaned:
        raise ValueError(f'At least one {field.replace("_", " ")} entry is required.')
    return cleaned


def re_split_lines(value):
    return value.replace(',', '\n').splitlines()


def parse_preferences(form):
    try:
        minimum_score = int(form.get('minimum_match_score', DEFAULT_PREFERENCES['minimum_match_score']))
        daily_cap = int(form.get('daily_send_cap', DEFAULT_PREFERENCES['daily_send_cap']))
    except (TypeError, ValueError) as error:
        raise ValueError('Minimum score and daily send cap must be whole numbers.') from error
    if not 0 <= minimum_score <= 100:
        raise ValueError('Minimum match score must be between 0 and 100.')
    if not 0 <= daily_cap <= 50:
        raise ValueError('Daily send cap must be between 0 and 50.')

    getlist = getattr(form, 'getlist', None)
    if getlist:
        enabled_sources = getlist('enabled_sources')
    else:
        enabled_sources = form.get('enabled_sources', DEFAULT_PREFERENCES['enabled_sources'])
    if isinstance(enabled_sources, str):
        enabled_sources = [enabled_sources] if enabled_sources else []
    allowed_sources = set(SOURCE_REGISTRY)
    enabled_sources = list(dict.fromkeys(str(source) for source in enabled_sources if str(source) in allowed_sources))

    return {
        'target_titles': _list_value(form.get('target_titles', DEFAULT_PREFERENCES['target_titles']), 'target_titles'),
        'keywords': _list_value(form.get('keywords', DEFAULT_PREFERENCES['keywords']), 'keywords'),
        'excluded_keywords': _list_value(form.get('excluded_keywords', []), 'excluded_keywords'),
        'locations': _list_value(form.get('locations', DEFAULT_PREFERENCES['locations']), 'locations'),
        'remote_only': str(form.get('remote_only', '')).casefold() in {'on', 'true', '1', 'yes'},
        'minimum_match_score': minimum_score,
        'excluded_companies': _list_value(form.get('excluded_companies', []), 'excluded_companies'),
        'daily_send_cap': daily_cap,
        'enabled_sources': enabled_sources,
    }


class JobFinderService:
    SOURCE_REQUEST_LIMIT = 4

    def __init__(self, connection_factory=None, sources=None):
        self.connection_factory = connection_factory or connect_database
        self.sources = sources or {key: source_class() for key, source_class in SOURCE_REGISTRY.items()}

    def get_preferences(self):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute('INSERT INTO job_finder_preferences (id) VALUES (1) ON CONFLICT (id) DO NOTHING')
            cursor.execute('SELECT * FROM job_finder_preferences WHERE id=1')
            row = cursor.fetchone()
            connection.commit()
            if not row:
                return dict(DEFAULT_PREFERENCES)
            preferences = {}
            for field in PREFERENCE_FIELDS:
                value = row.get(field)
                if field in {'remote_only', 'minimum_match_score', 'daily_send_cap'}:
                    preferences[field] = value
                else:
                    if isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except ValueError:
                            value = []
                    preferences[field] = value if isinstance(value, list) else []
            return preferences
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def save_preferences(self, preferences):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                'INSERT INTO job_finder_preferences '
                '(id, target_titles, keywords, excluded_keywords, locations, remote_only, '
                'minimum_match_score, excluded_companies, daily_send_cap, enabled_sources, updated_at) '
                'VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) '
                'ON CONFLICT (id) DO UPDATE SET target_titles=EXCLUDED.target_titles, '
                'keywords=EXCLUDED.keywords, excluded_keywords=EXCLUDED.excluded_keywords, '
                'locations=EXCLUDED.locations, remote_only=EXCLUDED.remote_only, '
                'minimum_match_score=EXCLUDED.minimum_match_score, '
                'excluded_companies=EXCLUDED.excluded_companies, daily_send_cap=EXCLUDED.daily_send_cap, '
                'enabled_sources=EXCLUDED.enabled_sources, updated_at=NOW()',
                (Json(preferences['target_titles']), Json(preferences['keywords']),
                 Json(preferences['excluded_keywords']), Json(preferences['locations']),
                 preferences['remote_only'], preferences['minimum_match_score'],
                 Json(preferences['excluded_companies']), preferences['daily_send_cap'],
                 Json(preferences['enabled_sources'])),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def list_jobs(self, status=None, limit=100):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            if status:
                cursor.execute(
                    'SELECT * FROM job_finder_jobs WHERE status=%s '
                    'ORDER BY score DESC NULLS LAST, posted_at DESC NULLS LAST, created_at DESC LIMIT %s',
                    (status, limit),
                )
            else:
                cursor.execute(
                    'SELECT * FROM job_finder_jobs '
                    'ORDER BY score DESC NULLS LAST, posted_at DESC NULLS LAST, created_at DESC LIMIT %s',
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def recent_source_runs(self, limit=10):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                'SELECT DISTINCT ON (source_key) source_key, fetched_at, succeeded, error_code '
                'FROM job_finder_source_runs ORDER BY source_key, fetched_at DESC LIMIT %s',
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def allow_action(self, actor_id, action, limit, window_seconds):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                'SELECT pg_advisory_xact_lock(hashtext(%s))',
                (f'job-finder-rate:{actor_id}:{action}',),
            )
            cursor.execute(
                'SELECT window_started_at, request_count FROM job_finder_rate_limits '
                'WHERE actor_id=%s AND action=%s FOR UPDATE',
                (str(actor_id), action),
            )
            row = cursor.fetchone()
            now = datetime.now(timezone.utc)
            if row:
                window_started = row[0]
                if window_started.tzinfo is None:
                    window_started = window_started.replace(tzinfo=timezone.utc)
                if (now - window_started).total_seconds() < window_seconds and row[1] >= limit:
                    connection.commit()
                    return False
                if (now - window_started).total_seconds() < window_seconds:
                    cursor.execute(
                        'UPDATE job_finder_rate_limits SET request_count=request_count+1 '
                        'WHERE actor_id=%s AND action=%s',
                        (str(actor_id), action),
                    )
                else:
                    cursor.execute(
                        'UPDATE job_finder_rate_limits SET window_started_at=%s, request_count=1 '
                        'WHERE actor_id=%s AND action=%s',
                        (now, str(actor_id), action),
                    )
            else:
                cursor.execute(
                    'INSERT INTO job_finder_rate_limits (actor_id, action, window_started_at, request_count) '
                    'VALUES (%s, %s, %s, 1)',
                    (str(actor_id), action, now),
                )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def _reserve_source_request(self, source_key):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM job_finder_source_runs "
                "WHERE source_key=%s AND fetched_at >= NOW() - INTERVAL '24 hours'",
                (source_key,),
            )
            if cursor.fetchone()[0] >= self.SOURCE_REQUEST_LIMIT:
                connection.rollback()
                return None
            cursor.execute(
                'INSERT INTO job_finder_source_runs (source_key, succeeded) VALUES (%s, FALSE) RETURNING id',
                (source_key,),
            )
            run_id = cursor.fetchone()[0]
            connection.commit()
            return run_id
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def _finish_source_request(self, run_id, succeeded, error_code=None):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                'UPDATE job_finder_source_runs SET succeeded=%s, error_code=%s WHERE id=%s',
                (succeeded, error_code, run_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def _store_new_jobs(self, jobs):
        if not jobs:
            return []
        connection = self.connection_factory()
        cursor = None
        inserted = []
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            for job in jobs:
                cursor.execute(
                    'INSERT INTO job_finder_jobs '
                    '(source_key, source_name, source_url, external_id, posting_url, posting_url_key, '
                    'apply_url, application_email, title, title_key, company, company_key, location, '
                    'job_type, posted_at, status, created_at, updated_at) '
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'found', NOW(), NOW()) "
                    'ON CONFLICT DO NOTHING RETURNING id',
                    (job['source_key'], job['source_name'], job['source_url'], job['external_id'],
                     job['posting_url'], job['posting_url_key'], job['apply_url'], job['application_email'],
                     job['title'], job['title_key'], job['company'], job['company_key'], job['location'],
                     job['job_type'], job['posted_at']),
                )
                row = cursor.fetchone()
                if row:
                    inserted.append({**job, 'id': row['id']})
            connection.commit()
            return inserted
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def fetch_new_jobs(self):
        preferences = self.get_preferences()
        selected = [key for key in preferences['enabled_sources'] if key in self.sources]
        discovered = []
        errors = {}
        throttled = []
        for source_key in selected:
            source = self.sources[source_key]
            if not source.has_fresh_cache():
                run_id = self._reserve_source_request(source_key)
                if run_id is None:
                    throttled.append(source_key)
                    continue
            else:
                run_id = None
            try:
                discovered.extend(source.fetch())
                if run_id is not None:
                    self._finish_source_request(run_id, True)
            except Exception as error:
                logger.warning('Job source %s failed (%s)', source_key, type(error).__name__)
                errors[source_key] = type(error).__name__
                if run_id is not None:
                    try:
                        self._finish_source_request(run_id, False, type(error).__name__)
                    except Exception:
                        logger.exception('Could not record job source failure for %s', source_key)

        unique_jobs = deduplicate_jobs(discovered)
        inserted = self._store_new_jobs(unique_jobs)
        return {
            'sources': len(selected),
            'discovered': len(unique_jobs),
            'inserted': len(inserted),
            'source_errors': errors,
            'throttled_sources': throttled,
            'new_jobs': inserted,
        }


job_finder_service = JobFinderService()
