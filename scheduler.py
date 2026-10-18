import hashlib
import logging
from datetime import datetime, timezone
from threading import Lock

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

UTC = timezone.utc  # noqa: UP017

logger = logging.getLogger(__name__)


class PostgresJobScheduler:
    GLOBAL_LOCK_KEY = 71843829100422
    LOCK_RETRY_SECONDS = 15

    def __init__(self, connection_factory, jobs, on_failure=None):
        self.connection_factory = connection_factory
        self.jobs = jobs
        self.on_failure = on_failure
        self.scheduler = None
        self._leader_connection = None
        self._last_lock_attempt = None
        self._guard = Lock()

    @staticmethod
    def _job_lock_key(job_name):
        digest = hashlib.sha256(f'portfolio-job:{job_name}'.encode()).digest()[:8]
        return int.from_bytes(digest, byteorder='big', signed=True)

    @staticmethod
    def _utc(value):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def start_if_needed(self):
        if self.scheduler and self.scheduler.running:
            return True
        now = datetime.now(UTC)
        if self._last_lock_attempt and (now - self._last_lock_attempt).total_seconds() < self.LOCK_RETRY_SECONDS:
            return False

        with self._guard:
            if self.scheduler and self.scheduler.running:
                return True
            self._last_lock_attempt = now
            connection = None
            cursor = None
            acquired = False
            try:
                connection = self.connection_factory()
                cursor = connection.cursor()
                cursor.execute('SELECT pg_try_advisory_lock(%s)', (self.GLOBAL_LOCK_KEY,))
                acquired = bool(cursor.fetchone()[0])
                connection.commit()
                cursor.close()
                cursor = None
                if not acquired:
                    connection.close()
                    return False

                self._leader_connection = connection
                self.scheduler = BackgroundScheduler(timezone=UTC)
                for job_name, definition in self.jobs.items():
                    cron = definition.get('cron')
                    trigger = CronTrigger(**cron) if cron else 'interval'
                    next_run = self._next_run(job_name, definition['interval'], cron)
                    job_options = {'trigger': trigger} if cron else {
                        'trigger': trigger,
                        'seconds': definition['interval'].total_seconds(),
                    }
                    self.scheduler.add_job(
                        self.run_job,
                        **job_options,
                        id=job_name,
                        args=[job_name],
                        next_run_time=next_run,
                        coalesce=True,
                        max_instances=1,
                        misfire_grace_time=None,
                    )
                self.scheduler.add_job(
                    self._check_leadership,
                    trigger='interval',
                    seconds=60,
                    id='scheduler-leadership-check',
                    max_instances=1,
                )
                self.scheduler.start()
                return True
            except Exception:
                logger.exception('Could not start the PostgreSQL-backed scheduler')
                if cursor:
                    cursor.close()
                if connection:
                    if acquired:
                        try:
                            unlock_cursor = connection.cursor()
                            unlock_cursor.execute('SELECT pg_advisory_unlock(%s)', (self.GLOBAL_LOCK_KEY,))
                            connection.commit()
                            unlock_cursor.close()
                        except Exception:
                            logger.exception('Could not release scheduler advisory lock')
                    connection.close()
                self._leader_connection = None
                self.scheduler = None
                return False

    def _check_leadership(self):
        connection = self._leader_connection
        cursor = None
        try:
            if connection is None or connection.closed:
                raise ConnectionError('Scheduler advisory-lock connection is closed')
            cursor = connection.cursor()
            cursor.execute('SELECT 1')
            cursor.fetchone()
            connection.commit()
            return True
        except Exception:
            logger.exception('Scheduler advisory-lock connection was lost')
            self.stop()
            return False
        finally:
            if cursor:
                cursor.close()

    def stop(self):
        scheduler = self.scheduler
        self.scheduler = None
        if scheduler and scheduler.running:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                logger.exception('Could not stop the background scheduler')

        connection = self._leader_connection
        self._leader_connection = None
        if connection:
            try:
                if not connection.closed:
                    cursor = connection.cursor()
                    cursor.execute('SELECT pg_advisory_unlock(%s)', (self.GLOBAL_LOCK_KEY,))
                    connection.commit()
                    cursor.close()
            except Exception:
                logger.exception('Could not release scheduler advisory lock')
            finally:
                connection.close()
        self._last_lock_attempt = None

    def _next_run(self, job_name, interval, cron=None):
        connection = self._leader_connection
        cursor = connection.cursor()
        cursor.execute('SELECT last_run_at FROM job_runs WHERE job_name=%s', (job_name,))
        row = cursor.fetchone()
        last_run = self._utc(row[0]) if row else None
        now = datetime.now(UTC)
        if cron:
            next_run = CronTrigger(**cron).get_next_fire_time(last_run, now)
        else:
            next_run = now if last_run is None or now >= last_run + interval else last_run + interval
        cursor.execute(
            "INSERT INTO job_runs (job_name, status, next_run_at) VALUES (%s, 'never', %s) "
            'ON CONFLICT (job_name) DO UPDATE SET next_run_at=EXCLUDED.next_run_at',
            (job_name, next_run),
        )
        connection.commit()
        cursor.close()
        return next_run

    def run_job(self, job_name):
        definition = self.jobs.get(job_name)
        if not definition:
            raise KeyError(f'Unknown scheduled job: {job_name}')

        connection = None
        cursor = None
        locked = False
        now = datetime.now(UTC)
        cron = definition.get('cron')
        next_run = (
            CronTrigger(**cron).get_next_fire_time(now, now)
            if cron else now + definition['interval']
        )
        try:
            connection = self.connection_factory()
            cursor = connection.cursor()
            cursor.execute('SELECT pg_try_advisory_lock(%s)', (self._job_lock_key(job_name),))
            locked = bool(cursor.fetchone()[0])
            connection.commit()
            if not locked:
                return False

            cursor.execute(
                "INSERT INTO job_runs (job_name, status, next_run_at) VALUES (%s, 'running', %s) "
                "ON CONFLICT (job_name) DO UPDATE SET status='running', last_error=NULL, next_run_at=EXCLUDED.next_run_at",
                (job_name, next_run),
            )
            connection.commit()
            definition['func']()
            cursor.execute(
                "UPDATE job_runs SET last_run_at=%s, status='success', next_run_at=%s, last_error=NULL WHERE job_name=%s",
                (datetime.now(UTC), next_run, job_name),
            )
            connection.commit()
            return True
        except Exception as error:
            logger.exception('Scheduled job %s failed', job_name)
            if connection:
                try:
                    connection.rollback()
                    if cursor:
                        cursor.execute(
                            "INSERT INTO job_runs (job_name, last_run_at, status, next_run_at, last_error) "
                            "VALUES (%s, %s, 'failed', %s, %s) ON CONFLICT (job_name) DO UPDATE "
                            "SET last_run_at=EXCLUDED.last_run_at, status='failed', next_run_at=EXCLUDED.next_run_at, last_error=EXCLUDED.last_error",
                            (job_name, datetime.now(UTC), next_run, str(error)[:2000]),
                        )
                        connection.commit()
                except Exception:
                    logger.exception('Could not record failure for scheduled job %s', job_name)
            if self.on_failure:
                try:
                    self.on_failure(job_name, error)
                except Exception:
                    logger.exception('Failure alert for scheduled job %s failed', job_name)
            return False
        finally:
            if cursor:
                try:
                    if locked:
                        cursor.execute('SELECT pg_advisory_unlock(%s)', (self._job_lock_key(job_name),))
                        connection.commit()
                finally:
                    cursor.close()
            if connection:
                connection.close()

    def statuses(self):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute('SELECT job_name, last_run_at, status, next_run_at, last_error FROM job_runs')
            rows = {row[0]: row for row in cursor.fetchall()}
            statuses = []
            for job_name, definition in self.jobs.items():
                row = rows.get(job_name)
                statuses.append({
                    'job_name': job_name,
                    'last_run_at': row[1] if row else None,
                    'status': row[2] if row else 'never',
                    'next_run_at': row[3] if row else None,
                    'last_error': row[4] if row else None,
                    'interval': definition['interval'],
                })
            return statuses
        finally:
            if cursor:
                cursor.close()
            connection.close()
