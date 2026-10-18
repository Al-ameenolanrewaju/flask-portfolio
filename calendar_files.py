import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc  # noqa: UP017


def _required_text(value, label, limit=500):
    cleaned = ' '.join(str(value or '').split())
    if len(cleaned) > limit:
        raise ValueError(f'{label} must be {limit} characters or fewer.')
    return cleaned


def validate_interview(data, default_timezone='Africa/Lagos'):
    timezone_name = _required_text(data.get('timezone') or default_timezone, 'Timezone', 100)
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError('Choose a valid IANA timezone.') from error
    try:
        local_start = datetime.fromisoformat(
            f"{data.get('date', '')}T{data.get('time', '')}"
        )
        if local_start.tzinfo:
            raise ValueError
        fold = int(data.get('fold', 0))
        if fold not in (0, 1):
            raise ValueError
        start = local_start.replace(tzinfo=zone, fold=fold)
    except (TypeError, ValueError) as error:
        raise ValueError('Enter a valid interview date and local time.') from error

    round_trip = start.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if round_trip != local_start:
        raise ValueError('That local time does not exist in the selected timezone.')

    try:
        duration = int(data.get('duration_minutes', 60))
    except (TypeError, ValueError) as error:
        raise ValueError('Duration must be a whole number of minutes.') from error
    if not 15 <= duration <= 480:
        raise ValueError('Duration must be between 15 and 480 minutes.')

    location = _required_text(data.get('location'), 'Location', 500)
    interviewer = _required_text(data.get('interviewer'), 'Interviewer', 250)
    meeting_url = _required_text(data.get('meeting_url'), 'Meeting link', 1000)
    if meeting_url and not re.fullmatch(r'https?://[^\s<>]+', meeting_url, re.IGNORECASE):
        raise ValueError('Meeting link must be an HTTP or HTTPS URL.')
    if not location and not meeting_url:
        raise ValueError('Enter a meeting link or location.')
    return {
        'starts_at': start.astimezone(UTC),
        'timezone': timezone_name,
        'duration_minutes': duration,
        'location': location,
        'meeting_url': meeting_url,
        'interviewer': interviewer,
    }


def _escape_text(value):
    return (
        str(value or '').replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n')
        .replace('\n', '\\n').replace(',', '\\,').replace(';', '\\;')
    )


def _fold_line(line, limit=75):
    pieces = []
    current = ''
    current_bytes = 0
    for character in line:
        encoded_length = len(character.encode('utf-8'))
        if current and current_bytes + encoded_length > limit:
            pieces.append(current)
            current = ''
            current_bytes = 1
        current += character
        current_bytes += encoded_length
    pieces.append(current)
    return '\r\n '.join(pieces)


def build_ics(interview, job, briefing_url, now=None):
    start = interview['starts_at'].astimezone(UTC)
    end = start + timedelta(minutes=interview['duration_minutes'])
    stamp = (now or datetime.now(UTC)).astimezone(UTC)
    summary = f"Interview: {job.get('title') or 'Role'} at {job.get('company') or 'Company'}"
    description = '\n'.join(filter(None, (
        f"Interviewer: {interview.get('interviewer')}",
        f"Meeting link: {interview.get('meeting_url')}" if interview.get('meeting_url') else '',
        f"Briefing: {briefing_url}",
    )))
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Portfolio//Interview Calendar//EN',
        'CALSCALE:GREGORIAN',
        'X-WR-TIMEZONE:' + _escape_text(interview['timezone']),
        'BEGIN:VEVENT',
        f"UID:{interview['uid']}",
        f'DTSTAMP:{stamp.strftime("%Y%m%dT%H%M%SZ")}',
        f'DTSTART:{start.strftime("%Y%m%dT%H%M%SZ")}',
        f'DTEND:{end.strftime("%Y%m%dT%H%M%SZ")}',
        'SUMMARY:' + _escape_text(summary),
        'DESCRIPTION:' + _escape_text(description),
        'LOCATION:' + _escape_text(interview.get('location')),
        f"URL:{briefing_url}",
        'BEGIN:VALARM',
        'TRIGGER:-P1D',
        'ACTION:DISPLAY',
        'DESCRIPTION:Interview in one day',
        'END:VALARM',
        'BEGIN:VALARM',
        'TRIGGER:-PT1H',
        'ACTION:DISPLAY',
        'DESCRIPTION:Interview in one hour',
        'END:VALARM',
        'END:VEVENT',
        'END:VCALENDAR',
    ]
    return '\r\n'.join(_fold_line(line) for line in lines) + '\r\n'