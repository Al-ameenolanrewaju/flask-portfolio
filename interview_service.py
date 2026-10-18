import uuid

from psycopg2.extras import RealDictCursor

from calendar_files import validate_interview


class InterviewService:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def list_for_job(self, job_id):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                'SELECT * FROM job_finder_interviews WHERE job_id=%s ORDER BY starts_at, id',
                (job_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def get(self, job_id, interview_id):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                'SELECT * FROM job_finder_interviews WHERE job_id=%s AND id=%s',
                (job_id, interview_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if cursor:
                cursor.close()
            connection.close()

    def save(self, job_id, data, default_timezone='Africa/Lagos', interview_id=None):
        event = validate_interview(data, default_timezone)
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT id FROM job_finder_jobs WHERE id=%s FOR UPDATE', (job_id,))
            if not cursor.fetchone():
                connection.rollback()
                return None
            if interview_id:
                cursor.execute(
                    'SELECT uid FROM job_finder_interviews WHERE id=%s AND job_id=%s FOR UPDATE',
                    (interview_id, job_id),
                )
                existing = cursor.fetchone()
                if not existing:
                    connection.rollback()
                    return None
                cursor.execute(
                    'UPDATE job_finder_interviews SET starts_at=%s, timezone=%s, duration_minutes=%s, '
                    'location=%s, meeting_url=%s, interviewer=%s, updated_at=NOW() '
                    'WHERE id=%s AND job_id=%s',
                    (
                        event['starts_at'], event['timezone'], event['duration_minutes'], event['location'],
                        event['meeting_url'], event['interviewer'], interview_id, job_id,
                    ),
                )
                saved_id = interview_id
            else:
                uid = f'interview-{uuid.uuid4()}@portfolio.local'
                cursor.execute(
                    'INSERT INTO job_finder_interviews '
                    '(job_id, uid, starts_at, timezone, duration_minutes, location, meeting_url, interviewer) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id',
                    (
                        job_id, uid, event['starts_at'], event['timezone'], event['duration_minutes'],
                        event['location'], event['meeting_url'], event['interviewer'],
                    ),
                )
                saved_id = cursor.fetchone()['id']
            connection.commit()
            return saved_id
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            connection.close()