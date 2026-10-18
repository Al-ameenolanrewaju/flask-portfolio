import html
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
UTC = timezone.utc  # noqa: UP017
CONTACT_LABELS = ('recruiter', 'client', 'collaboration', 'spam', 'other')


class WeeklyReportError(Exception):
    pass


def _absolute_base_url(config):
    value = str(config.get('PUBLIC_BASE_URL') or config.get('RENDER_EXTERNAL_HOSTNAME') or '').strip().rstrip('/')
    if value and not value.startswith(('http://', 'https://')):
        value = 'https://' + value
    if not value:
        raise WeeklyReportError("Set PUBLIC_BASE_URL or use Render's RENDER_EXTERNAL_HOSTNAME for dashboard links.")
    return value


class WeeklyReportService:
    def __init__(self, connection_factory, config_provider, email_sender, now=None, sleep=None):
        self.connection_factory = connection_factory
        self.config_provider = config_provider
        self.email_sender = email_sender
        self.now = now or (lambda: datetime.now(UTC))
        self.sleep = sleep or time.sleep

    def collect(self):
        config = self.config_provider()
        timezone_name = config.get('CALENDAR_TIMEZONE', 'Africa/Lagos')
        try:
            zone = ZoneInfo(timezone_name)
        except (TypeError, ZoneInfoNotFoundError):
            zone = ZoneInfo('Africa/Lagos')
        local_now = self.now().astimezone(zone)
        window_start = local_now - timedelta(days=7)
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT COUNT(*) AS count FROM job_finder_jobs WHERE created_at >= %s', (window_start,))
            found = cursor.fetchone()['count']
            cursor.execute(
                "SELECT COUNT(*) AS count FROM job_finder_send_audit WHERE status='sent' AND sent_at >= %s",
                (window_start,),
            )
            applications = cursor.fetchone()['count']
            cursor.execute(
                "SELECT COUNT(*) AS count FROM job_finder_replies WHERE received_at >= %s "
                "AND category NOT IN ('auto_reply', 'unrelated')",
                (window_start,),
            )
            replies = cursor.fetchone()['count']
            cursor.execute(
                'SELECT j.company, j.title, i.starts_at, i.timezone, i.location, i.meeting_url '
                'FROM job_finder_interviews i JOIN job_finder_jobs j ON j.id=i.job_id '
                'WHERE i.starts_at >= %s ORDER BY i.starts_at LIMIT 20',
                (local_now,),
            )
            upcoming = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT COUNT(*) AS count FROM job_finder_jobs WHERE status IN ('drafted', 'approved')")
            pending_job_drafts = cursor.fetchone()['count']
            cursor.execute(
                "SELECT COUNT(*) AS count FROM contact_messages "
                "WHERE triage_status='complete' AND reply_status IN ('pending', 'approved')"
            )
            pending_contact_drafts = cursor.fetchone()['count']
            cursor.execute(
                'SELECT triage_label, COUNT(*) AS count FROM contact_messages '
                'WHERE created_at >= %s GROUP BY triage_label',
                (window_start,),
            )
            contact_rows = cursor.fetchall()
            contacts = {label: 0 for label in CONTACT_LABELS}
            for row in contact_rows:
                label = row['triage_label'] if row['triage_label'] in contacts else 'other'
                contacts[label] += row['count']
            cursor.execute(
                "SELECT COUNT(*) FILTER (WHERE demo_link_status='broken') "
                "+ COUNT(*) FILTER (WHERE repo_link_status='broken') AS count FROM projects"
            )
            broken_links = cursor.fetchone()['count']
            cursor.execute(
                "SELECT job_name, last_run_at FROM job_runs WHERE status='failed' AND last_run_at >= %s "
                'ORDER BY last_run_at DESC',
                (window_start,),
            )
            failed_jobs = [dict(row) for row in cursor.fetchall()]
            return {
                'window_start': window_start,
                'window_end': local_now,
                'jobs_found': found,
                'applications_sent': applications,
                'replies': replies,
                'upcoming_interviews': upcoming,
                'pending_drafts': pending_job_drafts + pending_contact_drafts,
                'contact_messages_by_label': contacts,
                'broken_links': broken_links,
                'failed_scheduled_jobs': failed_jobs,
            }
        finally:
            if cursor:
                cursor.close()
            connection.close()

    @staticmethod
    def _has_activity(report):
        return any((
            report['jobs_found'], report['applications_sent'], report['replies'],
            report['upcoming_interviews'], report['pending_drafts'], report['broken_links'],
            report['failed_scheduled_jobs'], sum(report['contact_messages_by_label'].values()),
        ))

    @staticmethod
    def _html_report(report, dashboard_url):
        list_items = lambda values: ''.join(f'<li>{html.escape(str(value))}</li>' for value in values) or '<li>None</li>'
        interviews = [
            f"{event['starts_at']} · {event['company']} · {event['title']} · {event['timezone']}"
            for event in report['upcoming_interviews']
        ]
        failed = [f"{job['job_name']} · {job['last_run_at']}" for job in report['failed_scheduled_jobs']]
        contacts = [f'{label.title()}: {count}' for label, count in report['contact_messages_by_label'].items()]
        activity = (
            f"<p>Period: {html.escape(str(report['window_start']))} to {html.escape(str(report['window_end']))}</p>"
            f"<ul><li>Jobs found: {report['jobs_found']}</li>"
            f"<li>Applications sent: {report['applications_sent']}</li>"
            f"<li>Replies: {report['replies']}</li>"
            f"<li>Pending drafts: {report['pending_drafts']}</li>"
            f"<li>Broken links: {report['broken_links']}</li></ul>"
            f"<h2>Upcoming interviews</h2><ul>{list_items(interviews)}</ul>"
            f"<h2>Contact messages by label</h2><ul>{list_items(contacts)}</ul>"
            f"<h2>Failed scheduled jobs</h2><ul>{list_items(failed)}</ul>"
        )
        if not WeeklyReportService._has_activity(report):
            activity = '<p>No activity in the last seven days.</p>' + activity
        safe_url = html.escape(dashboard_url, quote=True)
        return f'<html><body><h1>Weekly portfolio report</h1>{activity}<p><a href="{safe_url}">Open Job Finder dashboard</a></p></body></html>'

    def send_weekly_report(self):
        config = self.config_provider()
        recipient = config.get('CONTACT_EMAIL')
        if not recipient:
            raise WeeklyReportError('CONTACT_EMAIL is required for weekly reports.')
        report = self.collect()
        dashboard_url = _absolute_base_url(config) + '/admin/job-finder/'
        payload = {
            'from': config.get('RESEND_FROM') or 'onboarding@resend.dev',
            'to': [recipient],
            'subject': 'Weekly portfolio and job search report',
            'html': self._html_report(report, dashboard_url),
        }
        for attempt in range(2):
            try:
                result = self.email_sender(payload)
                if result is False:
                    raise WeeklyReportError('Resend did not confirm report delivery.')
                return {'sent': True, 'attempts': attempt + 1, 'report': report}
            except Exception as error:
                if attempt == 0:
                    logger.warning('Weekly report email failed (%s); retrying once', type(error).__name__)
                    self.sleep(1)
                else:
                    logger.error('Weekly report email failed after retry (%s)', type(error).__name__)
                    raise WeeklyReportError('Weekly report could not be sent after one retry.') from error
        return {'sent': False, 'attempts': 2, 'report': report}