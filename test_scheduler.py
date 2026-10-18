from datetime import datetime, timedelta, timezone

from scheduler import PostgresJobScheduler

UTC = timezone.utc  # noqa: UP017


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.statement = ''

    def execute(self, statement, params=None):
        self.statement = statement
        self.connection.statements.append((statement, params))

    def fetchone(self):
        if 'pg_try_advisory_lock' in self.statement:
            return (True,)
        if 'SELECT last_run_at' in self.statement:
            return (datetime.now(UTC) - timedelta(days=8),)
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.statements = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class FakeBackgroundScheduler:
    def __init__(self, **kwargs):
        self.running = False
        self.jobs = []

    def add_job(self, func, **kwargs):
        self.jobs.append({'func': func, **kwargs})

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False


def test_scheduler_runs_overdue_jobs_immediately(monkeypatch):
    import scheduler as scheduler_module

    connection = FakeConnection()
    monkeypatch.setattr(scheduler_module, 'BackgroundScheduler', FakeBackgroundScheduler)
    service = PostgresJobScheduler(
        lambda: connection,
        {'weekly-check': {'func': lambda: None, 'interval': timedelta(days=7)}},
    )

    assert service.start_if_needed()
    scheduled_job = next(job for job in service.scheduler.jobs if job.get('id') == 'weekly-check')
    assert scheduled_job['next_run_time'] <= datetime.now(UTC)
    service.stop()
    assert connection.closed


def test_failed_job_is_recorded_and_alert_failure_does_not_escape():
    connection = FakeConnection()
    alerts = []

    def fail_job():
        raise RuntimeError('upstream unavailable')

    service = PostgresJobScheduler(
        lambda: connection,
        {'broken-job': {'func': fail_job, 'interval': timedelta(days=1)}},
        on_failure=lambda name, error: alerts.append((name, str(error))),
    )

    assert service.run_job('broken-job') is False
    assert alerts == [('broken-job', 'upstream unavailable')]
    assert any("'failed'" in statement for statement, _ in connection.statements)
    assert connection.closed