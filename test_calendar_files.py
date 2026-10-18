from datetime import datetime, timezone

import pytest

from calendar_files import build_ics, validate_interview

UTC = timezone.utc  # noqa: UP017


def test_interview_timezone_converts_to_the_correct_utc_instant():
    event = validate_interview({
        'date': '2026-10-19', 'time': '09:30', 'timezone': 'Africa/Lagos',
        'duration_minutes': '60', 'location': 'Lagos office', 'interviewer': 'Ada',
    })

    assert event['starts_at'] == datetime(2026, 10, 19, 8, 30, tzinfo=UTC)
    assert event['timezone'] == 'Africa/Lagos'


def test_interview_rejects_invalid_timezone_and_nonexistent_dst_time():
    with pytest.raises(ValueError, match='IANA timezone'):
        validate_interview({'date': '2026-10-19', 'time': '09:30', 'timezone': 'Not/AZone', 'location': 'Office'})
    with pytest.raises(ValueError, match='does not exist'):
        validate_interview({
            'date': '2026-03-08', 'time': '02:30', 'timezone': 'America/New_York', 'location': 'Office',
        })


def test_ics_has_stable_uid_alarms_escaped_text_and_valid_crlf_folding():
    interview = {
        'uid': 'interview-7@example.test',
        'starts_at': datetime(2026, 10, 19, 8, 30, tzinfo=UTC),
        'timezone': 'Africa/Lagos',
        'duration_minutes': 60,
        'location': 'Room A, Floor 2; Lagos',
        'meeting_url': 'https://meet.example.test/room',
        'interviewer': 'Ada Example',
    }
    ics = build_ics(
        interview,
        {'title': 'Python Developer', 'company': 'Acme'},
        'https://portfolio.example.test/admin/job-finder/jobs/2/briefing',
        now=datetime(2026, 10, 18, tzinfo=UTC),
    )

    assert ics.endswith('\r\n')
    assert 'UID:interview-7@example.test\r\n' in ics
    assert 'DTSTART:20261019T083000Z\r\n' in ics
    assert 'TRIGGER:-P1D\r\n' in ics
    assert 'TRIGGER:-PT1H\r\n' in ics
    unfolded = ics.replace('\r\n ', '')
    assert 'Briefing: https://portfolio.example.test/admin/job-finder/jobs/2/briefing' in unfolded
    assert 'Room A\\, Floor 2\\; Lagos' in unfolded
    assert all(len(line.encode('utf-8')) <= 75 for line in ics.rstrip('\r\n').split('\r\n'))