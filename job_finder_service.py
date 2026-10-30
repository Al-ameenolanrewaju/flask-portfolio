import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from config import Config
from groq_client import (
    GroqClient,
    GroqDailyCapReached,
    GroqError,
    GroqRateLimitExceeded,
)
from job_finder_matcher import match_and_draft, prefilter_job
from job_finder_sources import SOURCE_REGISTRY, deduplicate_jobs

UTC = timezone.utc  # noqa: UP017

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


MASTER_PROFILE_DEFAULT = {
    'full_name': 'unknown',
    'email': 'unknown',
    'phone': 'unknown',
    'city_country': 'unknown',
    'links': {
        'portfolio': 'unknown',
        'github': 'unknown',
        'linkedin': 'unknown',
    },
    'education': 'unknown',
    'work_history': [],
    'achievements': [],
    'skills': [],
    'languages': [],
    'availability': 'unknown',
    'start_date': 'unknown',
    'notice_period': 'unknown',
    'work_authorization': 'unknown',
    'preferred_work_mode': 'unknown',
    'salary_expectation': 'unknown',
    'projects': [],
    'summary': 'unknown',
}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.replace('\r', '\n').split('\n') if item.strip()]
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            text = _as_text(item)
            if text and text != 'unknown':
                items.append(text)
        return items
    return []


def _as_text(value, default='unknown'):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _unknown_if_empty(value, default='unknown'):
    return _as_text(value, default) if value not in (None, '', []) else default


class JobFinderService:
    SOURCE_REQUEST_LIMIT = 4

    def __init__(self, connection_factory=None, sources=None, groq_client_factory=GroqClient):
        self.connection_factory = connection_factory or connect_database
        self.sources = sources or {key: source_class() for key, source_class in SOURCE_REGISTRY.items()}
        self.groq_client_factory = groq_client_factory
        self.groq_request_guard = None

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

    def job_status_counts(self):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute('SELECT status, COUNT(*) FROM job_finder_jobs GROUP BY status')
            counts = {status: 0 for status in (
                'found', 'drafted', 'approved', 'applied', 'interview', 'rejected', 'ignored',
            )}
            counts.update({status: count for status, count in cursor.fetchall() if status in counts})
            counts['total'] = sum(counts.values())
            return counts
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def list_jobs(self, status=None, limit=25, offset=0):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            if status:
                cursor.execute(
                    'SELECT * FROM job_finder_jobs WHERE status=%s '
                    'ORDER BY score DESC NULLS LAST, posted_at DESC NULLS LAST, created_at DESC LIMIT %s OFFSET %s',
                    (status, limit, offset),
                )
            else:
                cursor.execute(
                    'SELECT * FROM job_finder_jobs '
                    'ORDER BY score DESC NULLS LAST, posted_at DESC NULLS LAST, created_at DESC LIMIT %s OFFSET %s',
                    (limit, offset),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def update_review(self, job_id, action, cover_letter='', pitch_lines=None, notes='', follow_up_date=None):
        allowed_actions = {
            'save', 'approve', 'ignore', 'mark_applied', 'interview', 'reject',
        }
        if action not in allowed_actions:
            raise ValueError('Unknown Job Finder review action.')
        cover_letter = str(cover_letter or '').strip()[:8000]
        notes = str(notes or '').strip()[:4000]
        if isinstance(pitch_lines, str):
            pitch_lines = [line.strip() for line in pitch_lines.splitlines() if line.strip()]
        pitch_lines = [str(line).strip()[:240] for line in (pitch_lines or []) if str(line).strip()][:3]

        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                'SELECT status, cover_letter, pitch FROM job_finder_jobs WHERE id=%s FOR UPDATE',
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                connection.rollback()
                return False

            current_status = row['status']
            if action == 'approve':
                if not cover_letter or len(pitch_lines) != 3:
                    raise ValueError('Add a cover letter and exactly three pitch lines before approval.')
                status = 'approved'
            elif action == 'ignore':
                status = 'ignored'
            elif action == 'mark_applied':
                status = 'applied'
            elif action == 'interview':
                status = 'interview'
            elif action == 'reject':
                status = 'rejected'
            elif current_status == 'approved' and (
                cover_letter != (row.get('cover_letter') or '')
                or '\n'.join(pitch_lines) != (row.get('pitch') or '')
            ):
                status = 'drafted'
            else:
                status = current_status

            cursor.execute(
                'UPDATE job_finder_jobs SET cover_letter=%s, pitch=%s, notes=%s, follow_up_date=%s, '
                'status=%s, updated_at=NOW() WHERE id=%s',
                (cover_letter, '\n'.join(pitch_lines), notes, follow_up_date, status, job_id),
            )
            connection.commit()
            return status
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def get_job(self, job_id):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT * FROM job_finder_jobs WHERE id=%s', (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def normalize_master_profile(self, profile):
        if not profile:
            return dict(MASTER_PROFILE_DEFAULT)
        links = profile.get('links') or {}
        normalized = {
            'full_name': _unknown_if_empty(profile.get('full_name')),
            'email': _unknown_if_empty(profile.get('email')),
            'phone': _unknown_if_empty(profile.get('phone')),
            'city_country': _unknown_if_empty(profile.get('city_country')),
            'links': {
                'portfolio': _unknown_if_empty(links.get('portfolio')),
                'github': _unknown_if_empty(links.get('github')),
                'linkedin': _unknown_if_empty(links.get('linkedin')),
            },
            'education': _unknown_if_empty(profile.get('education')),
            'work_history': _as_list(profile.get('work_history')),
            'achievements': _as_list(profile.get('achievements')),
            'skills': _as_list(profile.get('skills')),
            'languages': _as_list(profile.get('languages')),
            'availability': _unknown_if_empty(profile.get('availability')),
            'start_date': _unknown_if_empty(profile.get('start_date')),
            'notice_period': _unknown_if_empty(profile.get('notice_period')),
            'work_authorization': _unknown_if_empty(profile.get('work_authorization')),
            'preferred_work_mode': _unknown_if_empty(profile.get('preferred_work_mode')),
            'salary_expectation': _unknown_if_empty(profile.get('salary_expectation')),
            'projects': _as_list(profile.get('projects')),
            'summary': _unknown_if_empty(profile.get('summary')),
        }
        if not normalized['work_history']:
            normalized['work_history'] = []
        if not normalized['projects']:
            normalized['projects'] = []
        if not normalized['skills']:
            normalized['skills'] = []
        return normalized

    def get_master_profile(self):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT content FROM site_content WHERE section_name='master_profile' LIMIT 1",
            )
            row = cursor.fetchone()
            if not row or not row.get('content'):
                return dict(MASTER_PROFILE_DEFAULT)
            try:
                profile = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
            except (TypeError, ValueError):
                return dict(MASTER_PROFILE_DEFAULT)
            return self.normalize_master_profile(profile)
        finally:
            if cursor:
                cursor.close()
            if connection is not None:
                connection.close()

    def save_master_profile(self, profile):
        normalized = self.normalize_master_profile(profile)
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT id FROM site_content WHERE section_name='master_profile' LIMIT 1",
            )
            row = cursor.fetchone()
            payload = json.dumps(normalized, ensure_ascii=True, sort_keys=True)
            if row:
                cursor.execute(
                    "UPDATE site_content SET content=%s, title=%s WHERE id=%s",
                    (payload, 'Master Profile', row[0]),
                )
            else:
                cursor.execute(
                    "INSERT INTO site_content (section_name, title, content) VALUES ('master_profile', 'Master Profile', %s)",
                    (payload,),
                )
            connection.commit()
            return normalized
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def build_tailored_cv_data(self, job, profile):
        normalized = self.normalize_master_profile(profile)
        skills = normalized.get('skills') or ['unknown']
        project_entries = []
        for project in normalized.get('projects') or []:
            if isinstance(project, dict):
                project_entries.append({
                    'title': _unknown_if_empty(project.get('title')),
                    'description': _unknown_if_empty(project.get('description')),
                    'technologies': _as_list(project.get('technologies')) or skills[:5],
                })
            else:
                project_entries.append({'title': str(project), 'description': 'Profile project', 'technologies': skills[:5]})
        if not project_entries:
            project_entries.append({'title': 'Portfolio project', 'description': 'Profile project', 'technologies': skills[:5]})
        return {
            'name': normalized.get('full_name', 'unknown'),
            'about': normalized.get('summary', 'unknown'),
            'skills': {'Core': skills},
            'projects': project_entries,
            'contact': normalized.get('email', 'unknown'),
        }

    def build_application_pack(self, job, profile, groq_client=None):
        normalized = self.normalize_master_profile(profile)
        if groq_client is None:
            groq_client = self.groq_client_factory(
                os.environ.get('GROQ_API_KEY', 'test-key'),
                os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile'),
            )
        prompt = (
            'Write a concise application pack for this job using only the candidate profile provided. '
            'Never invent or assume facts. Replace missing values with the exact word "unknown". '
            'Do not fill salary, visa status, work authorization, or any legal/personal questions automatically; use "needs my answer" instead. '
            'Use plain, natural English under 250 words for letters. Return JSON only with keys: '
            'cover_letter, email_subject, email_body, form_answers, linkedin_message, follow_up_email, interview_prep, cv_data.\n'
            f'<PROFILE>{json.dumps(normalized, ensure_ascii=True, sort_keys=True)}</PROFILE>\n'
            f'<JOB>{json.dumps({"title": job.get("title", ""), "company": job.get("company", ""), "description": str(job.get("description", ""))[:12000]}, ensure_ascii=True, sort_keys=True)}</JOB>'
        )
        try:
            result = groq_client.generate_json(prompt, before_request=self.groq_request_guard)
        except Exception:  # noqa: BLE001
            result = {}
        cover_letter = str(result.get('cover_letter') or '').strip() or (
            f"Dear hiring team,\n\nI am interested in the {job.get('title', 'role')} opportunity at {job.get('company', 'your company')}. "
            f"My background includes {', '.join(normalized.get('skills')[:4]) if normalized.get('skills') else 'unknown'} and I would value the chance to contribute to the team.\n\nThank you for considering my application."
        )
        if normalized.get('full_name') and normalized.get('full_name') != 'unknown' and normalized.get('full_name') not in cover_letter:
            cover_letter = cover_letter.replace(
                'Dear hiring team,',
                f"Dear hiring team,\n\nMy name is {normalized.get('full_name')}.",
                1,
            )
        email_subject = str(result.get('email_subject') or f"Application for {job.get('title', 'role')}").strip()
        email_body = str(
            result.get('email_body')
            or f"Hi team,\n\nI am applying for the {job.get('title', 'role')} role.\n\nThank you for your consideration."
        ).strip()
        if normalized.get('full_name') and normalized.get('full_name') != 'unknown' and normalized.get('full_name') not in email_body:
            email_body = f"Hi team,\n\nMy name is {normalized.get('full_name')}.\n\n{email_body}"
        form_answers = result.get('form_answers') or {}
        safe_answers = {
            'why_this_company': _unknown_if_empty(form_answers.get('why_this_company', 'unknown')),
            'why_this_role': _unknown_if_empty(form_answers.get('why_this_role', 'unknown')),
            'biggest_project': _unknown_if_empty(form_answers.get('biggest_project', 'unknown')),
            'strengths': _unknown_if_empty(form_answers.get('strengths', 'unknown')),
            'availability': _unknown_if_empty(form_answers.get('availability', normalized.get('availability', 'unknown'))),
            'salary_expectation': 'needs my answer',
            'work_authorization': 'needs my answer',
            'visa_status': 'needs my answer',
            'notice_period': 'needs my answer',
            'preferred_work_mode': normalized.get('preferred_work_mode', 'unknown') if normalized.get('preferred_work_mode') else 'unknown',
        }
        linkedin_message = str(result.get('linkedin_message') or f"Hi, I am very interested in the {job.get('title', 'role')} opportunity and would welcome a conversation.").strip()
        if normalized.get('full_name') and normalized.get('full_name') != 'unknown' and normalized.get('full_name') not in linkedin_message:
            linkedin_message = f"Hi, my name is {normalized.get('full_name')}. {linkedin_message}"
        follow_up_email = str(result.get('follow_up_email') or 'Thank you again for your time. I would welcome the opportunity to continue the conversation.').strip()
        interview_prep = result.get('interview_prep') or {'questions': ['Tell me about your most relevant project.']}
        if not isinstance(interview_prep, dict):
            interview_prep = {'questions': [str(interview_prep)]}
        if 'questions' not in interview_prep or not isinstance(interview_prep['questions'], list):
            interview_prep['questions'] = ['Tell me about your most relevant project.']
        cv_data = result.get('cv_data') or self.build_tailored_cv_data(job, normalized)
        pack = {
            'cover_letter': cover_letter[:1800],
            'email_subject': email_subject[:200],
            'email_body': email_body[:2000],
            'answers': safe_answers,
            'linkedin_message': linkedin_message[:1200],
            'follow_up_email': follow_up_email[:2000],
            'interview_prep': interview_prep,
            'cv_data': self.build_tailored_cv_data(job, normalized) if not cv_data else cv_data,
            'status': 'pending',
            'version': 1,
        }
        return pack

    def get_application_pack(self, job_id):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                'SELECT * FROM job_finder_application_packs WHERE job_id=%s ORDER BY version DESC LIMIT 1',
                (job_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            payload = row.get('pack_json')
            if isinstance(payload, str):
                return json.loads(payload)
            return payload
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def save_application_pack(self, job_id, pack, posting_hash=None):
        if not pack:
            return None
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                'SELECT COALESCE(MAX(version), 0) + 1 FROM job_finder_application_packs WHERE job_id=%s',
                (job_id,),
            )
            row = cursor.fetchone()
            next_version = row[0] if row and row[0] is not None else 1
            cursor.execute(
                'INSERT INTO job_finder_application_packs (job_id, posting_hash, pack_json, version, status, created_at, updated_at) '
                'VALUES (%s, %s, %s, %s, %s, NOW(), NOW())',
                (job_id, posting_hash, json.dumps(pack, ensure_ascii=True, sort_keys=True), next_version, 'pending'),
            )
            connection.commit()
            return pack
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def refresh_application_pack(self, job_id, job, profile, groq_client=None):
        posting_hash = hashlib.sha256(
            json.dumps({
                'url': job.get('posting_url'),
                'company': job.get('company'),
                'title': job.get('title'),
                'description': job.get('description'),
            }, sort_keys=True, default=str).encode('utf-8')
        ).hexdigest()
        existing = self.get_application_pack(job_id)
        if existing and existing.get('posting_hash') == posting_hash:
            return existing
        pack = self.build_application_pack(job, profile, groq_client)
        pack['posting_hash'] = posting_hash
        self.save_application_pack(job_id, pack, posting_hash)
        return pack

    def begin_send(self, job_id, subject, message_body):
        preferences = self.get_preferences()
        daily_cap = int(preferences['daily_send_cap'])
        if daily_cap <= 0:
            raise ValueError('The daily application email cap is set to zero.')
        body_hash = hashlib.sha256(message_body.encode('utf-8')).hexdigest()
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('job-finder-send-cap',))
            cursor.execute('SELECT * FROM job_finder_jobs WHERE id=%s FOR UPDATE', (job_id,))
            job = cursor.fetchone()
            if not job:
                raise ValueError('Job was not found.')
            job = dict(job)
            if job['status'] != 'approved':
                raise ValueError('Only an approved job draft can be sent.')
            if not job.get('application_email'):
                raise ValueError('This posting has no application email. Use its apply link instead.')
            if not job.get('cover_letter'):
                raise ValueError('Add and approve a cover letter before sending.')

            cursor.execute(
                "SELECT COUNT(*) AS count FROM job_finder_send_audit "
                "WHERE status IN ('sending', 'sent') AND attempted_at >= date_trunc('day', NOW())"
            )
            if cursor.fetchone()['count'] >= daily_cap:
                raise ValueError('The configured daily application email cap has been reached.')

            cursor.execute(
                "SELECT COUNT(*) AS count FROM job_finder_send_audit a "
                'JOIN job_finder_jobs j ON j.id=a.job_id '
                "WHERE a.status IN ('sending', 'sent') "
                "AND a.attempted_at >= NOW() - INTERVAL '30 days' "
                'AND (a.job_id=%s OR (j.company_key <> %s AND j.company_key=%s))',
                (job_id, '', job.get('company_key') or ''),
            )
            if cursor.fetchone()['count']:
                raise ValueError('A job or company application was already sent within the last 30 days.')

            cursor.execute(
                'INSERT INTO job_finder_send_audit '
                '(job_id, status, recipient, subject, payload_hash, attempted_at) '
                "VALUES (%s, 'sending', %s, %s, %s, NOW()) RETURNING id",
                (job_id, job['application_email'], subject, body_hash),
            )
            audit_id = cursor.fetchone()['id']
            connection.commit()
            return job, audit_id
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def finish_send(self, audit_id, job_id, succeeded, provider_ref=None, error_code=None):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                'UPDATE job_finder_send_audit SET status=%s, provider_ref=%s, error_code=%s, '
                'sent_at=%s WHERE id=%s AND status=%s',
                ('sent' if succeeded else 'failed', provider_ref, error_code,
                datetime.now(UTC) if succeeded else None, audit_id, 'sending'),
            )
            if succeeded:
                cursor.execute(
                    "UPDATE job_finder_jobs SET status='applied', updated_at=NOW() "
                    "WHERE id=%s AND status='approved'",
                    (job_id,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
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
            now = datetime.now(UTC)
            if row:
                window_started = row[0]
                if window_started.tzinfo is None:
                    window_started = window_started.replace(tzinfo=UTC)
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

    def _load_public_profile(self):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT section_name, title, content FROM site_content "
                "WHERE section_name IN ('hero', 'about')"
            )
            content = {row['section_name']: dict(row) for row in cursor.fetchall()}
            cursor.execute('SELECT category, name FROM skills ORDER BY category, id')
            skill_rows = [dict(row) for row in cursor.fetchall()]
            skills = {}
            for row in skill_rows:
                skills.setdefault(row['category'], []).append(row['name'])
            cursor.execute(
                'SELECT title, description, github_full_name, languages, topics '
                'FROM projects WHERE is_visible=TRUE ORDER BY sort_order, title'
            )
            projects = []
            repositories = []
            for row in cursor.fetchall():
                languages = row.get('languages') or []
                topics = row.get('topics') or []
                if isinstance(languages, str):
                    try:
                        languages = json.loads(languages)
                    except ValueError:
                        languages = []
                if isinstance(topics, str):
                    try:
                        topics = json.loads(topics)
                    except ValueError:
                        topics = []
                project = {
                    'title': str(row.get('title') or '')[:240],
                    'description': str(row.get('description') or '')[:1600],
                    'technologies': [str(value)[:80] for value in languages + topics if value],
                }
                projects.append(project)
                if row.get('github_full_name'):
                    repositories.append({
                        'name': str(row['github_full_name'])[:255],
                        'description': project['description'],
                        'technologies': project['technologies'],
                    })

            about = str(content.get('about', {}).get('content') or '')[:3000]
            public_name = str(content.get('hero', {}).get('title') or '')[:160]
            cv_text = '\n'.join([
                f'Name: {public_name}' if public_name else '',
                f'About: {about}' if about else '',
                'Skills: ' + '; '.join(f"{group}: {', '.join(values)}" for group, values in skills.items()),
                'Projects: ' + '; '.join(
                    f"{project['title']}: {project['description']} ({', '.join(project['technologies'])})"
                    for project in projects
                ),
            ])[:16000]
            return {
                'name': public_name,
                'about': about,
                'skills': skills,
                'projects': projects,
                'synced_repositories': repositories,
                'cv_text': cv_text,
            }
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def _unscored_jobs_for_urls(self, posting_url_keys):
        if not posting_url_keys:
            return []
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT * FROM job_finder_jobs WHERE status='found' AND score IS NULL "
                'AND posting_url_key = ANY(%s) ORDER BY posted_at DESC NULLS LAST, id',
                (list(posting_url_keys),),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def _save_match(self, job_id, score, reason, draft=None):
        pitch = '\n'.join(draft['pitch_lines']) if draft else None
        status = 'drafted' if draft else 'found'
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE job_finder_jobs SET score=%s, match_reason=%s, status=%s, "
                'cover_letter=%s, pitch=%s, scored_at=NOW(), drafted_at=%s, updated_at=NOW() '
                "WHERE id=%s AND status='found' AND score IS NULL",
                (score, reason, status, draft['cover_letter'] if draft else None, pitch,
                datetime.now(UTC) if draft else None, job_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def score_new_jobs(self, available_jobs, preferences=None, profile=None):
        preferences = preferences or self.get_preferences()
        keyed_jobs = {job['posting_url_key']: job for job in available_jobs if job.get('posting_url_key')}
        rows = self._unscored_jobs_for_urls(keyed_jobs)
        if not rows:
            return {'scored': 0, 'drafted': 0, 'unscored': 0, 'failures': 0}

        try:
            from flask import current_app
            ai_key = current_app.config.get('GROQ_API_KEY')
            model = current_app.config.get('GROQ_MODEL')
        except RuntimeError:
            ai_key = os.environ.get('GROQ_API_KEY')
            model = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
        if not ai_key:
            return {'scored': 0, 'drafted': 0, 'unscored': len(rows), 'failures': 0,
                    'reason': 'groq_unconfigured'}

        try:
            profile = profile if profile is not None else self._load_public_profile()
        except Exception:
            logger.exception('Could not load the public portfolio profile for Job Finder')
            return {'scored': 0, 'drafted': 0, 'unscored': len(rows), 'failures': len(rows),
                    'reason': 'profile_unavailable'}

        groq = self.groq_client_factory(ai_key, model)
        scored = 0
        drafted = 0
        failures = 0
        for row in rows:
            job = {**keyed_jobs.get(row['posting_url_key'], {}), **row}
            matches, reason = prefilter_job(job, preferences)
            if not matches:
                self._save_match(row['id'], 0, reason)
                scored += 1
                continue
            try:
                result = match_and_draft(
                    job, profile, preferences, groq,
                    before_request=self.groq_request_guard,
                )
                self._save_match(row['id'], result['score'], result['reason'], result['draft'])
                scored += 1
                drafted += int(result['draft'] is not None)
            except GroqDailyCapReached:
                logger.info('Job Finder scoring paused at the Groq daily cap')
                break
            except GroqRateLimitExceeded:
                logger.warning('Groq rate limited Job Finder matching; remaining jobs stay unscored')
                break
            except GroqError as error:
                logger.warning('Job Finder matching failed (%s); job remains unscored', type(error).__name__)
                failures += 1
            except Exception:
                logger.exception('Job Finder matching failed for job %s', row['id'])
                failures += 1
        return {'scored': scored, 'drafted': drafted, 'unscored': len(rows) - scored, 'failures': failures}

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
            except Exception as error:  # noqa: BLE001
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
            'available_jobs': unique_jobs,
        }

    def run_scheduled_scan(self):
        fetch_result = self.fetch_new_jobs()
        preferences = self.get_preferences()
        match_result = self.score_new_jobs(fetch_result['available_jobs'], preferences=preferences)
        return {
            'fetch': {key: value for key, value in fetch_result.items() if key != 'available_jobs'},
            'match': match_result,
        }


job_finder_service = JobFinderService()
