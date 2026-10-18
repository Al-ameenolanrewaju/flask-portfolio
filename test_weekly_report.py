from datetime import datetime, timezone

import pytest

import app as app_module
from weekly_report import WeeklyReportError, WeeklyReportService

UTC = timezone.utc  # noqa: UP017


class EmptyReportConnection:
    def cursor(self, cursor_factory=None):
        return EmptyReportCursor()

    def close(self):
        pass


class EmptyReportCursor:
    def __init__(self):
        self.query = ''

    def execute(self, sql, params=None):
        self.query = sql

    def fetchone(self):
        return {'count': 0}

    def fetchall(self):
        return []

    def close(self):
        pass


def test_weekly_report_handles_empty_data_and_includes_dashboard_link():
    captured = []
    service = WeeklyReportService(
        EmptyReportConnection,
        lambda: {
            'CALENDAR_TIMEZONE': 'Africa/Lagos', 'CONTACT_EMAIL': 'owner@example.test',
            'PUBLIC_BASE_URL': 'https://portfolio.example.test',
        },
        captured.append,
        now=lambda: datetime(2026, 10, 19, 8, 0, tzinfo=UTC),
        sleep=lambda seconds: None,
    )

    result = service.send_weekly_report()

    assert result['sent'] is True
    assert result['report']['jobs_found'] == 0
    assert result['report']['pending_drafts'] == 0
    assert all(count == 0 for count in result['report']['contact_messages_by_label'].values())
    assert 'No activity in the last seven days.' in captured[0]['html']
    assert 'https://portfolio.example.test/admin/job-finder/' in captured[0]['html']
    for section in (
        'Jobs found', 'Applications sent', 'Replies', 'Upcoming interviews',
        'Pending drafts', 'Contact messages by label', 'Broken links', 'Failed scheduled jobs',
    ):
        assert section in captured[0]['html']


def test_weekly_report_retries_failed_resend_once():
    attempts = []
    delays = []

    def sender(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise RuntimeError('temporary provider failure')
        return True

    service = WeeklyReportService(
        EmptyReportConnection,
        lambda: {
            'CALENDAR_TIMEZONE': 'Africa/Lagos', 'CONTACT_EMAIL': 'owner@example.test',
            'PUBLIC_BASE_URL': 'https://portfolio.example.test',
        },
        sender,
        now=lambda: datetime(2026, 10, 19, 8, 0, tzinfo=UTC),
        sleep=delays.append,
    )

    result = service.send_weekly_report()

    assert result['sent'] is True
    assert result['attempts'] == 2
    assert len(attempts) == 2
    assert delays == [1]


def test_weekly_report_does_not_retry_more_than_once():
    attempts = []

    def sender(payload):
        attempts.append(payload)
        raise RuntimeError('provider down')

    service = WeeklyReportService(
        EmptyReportConnection,
        lambda: {
            'CALENDAR_TIMEZONE': 'Africa/Lagos', 'CONTACT_EMAIL': 'owner@example.test',
            'PUBLIC_BASE_URL': 'https://portfolio.example.test',
        },
        sender,
        now=lambda: datetime(2026, 10, 19, 8, 0, tzinfo=UTC),
        sleep=lambda seconds: None,
    )

    with pytest.raises(WeeklyReportError, match='one retry'):
        service.send_weekly_report()

    assert len(attempts) == 2


def test_weekly_report_is_registered_for_monday_in_configured_timezone(monkeypatch):
    monkeypatch.setitem(app_module.app.config, 'CALENDAR_TIMEZONE', 'Africa/Lagos')
    monkeypatch.setitem(app_module.app.config, 'WEEKLY_REPORT_HOUR', '8')
    monkeypatch.setitem(app_module.app.config, 'WEEKLY_REPORT_MINUTE', '15')

    cron = app_module._weekly_report_cron()
    definition = app_module.job_scheduler.jobs['weekly-admin-report']

    assert cron['day_of_week'] == 'mon'
    assert cron['hour'] == 8
    assert cron['minute'] == 15
    assert cron['timezone'].key == 'Africa/Lagos'
    assert definition['cron']['day_of_week'] == 'mon'