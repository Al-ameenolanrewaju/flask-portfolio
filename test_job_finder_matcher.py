import pytest

from groq_client import GroqDailyCapReached, GroqError
from job_finder_matcher import match_and_draft, prefilter_job

PREFERENCES = {
    'target_titles': ['Python Developer', 'Backend Developer'],
    'keywords': ['Python', 'Flask', 'PostgreSQL'],
    'excluded_keywords': ['senior', 'staff', 'principal'],
    'excluded_companies': ['Excluded Corp'],
    'locations': ['Worldwide', 'Lagos, Nigeria'],
    'remote_only': True,
    'minimum_match_score': 70,
}
PROFILE = {
    'about': 'I build web apps using Python and Flask.',
    'skills': {'Backend': ['Python', 'Flask', 'PostgreSQL']},
    'projects': [{'title': 'Portfolio', 'description': 'Flask application.'}],
}
JOB = {
    'title': 'Python Backend Developer', 'company': 'Good Co', 'location': 'Worldwide',
    'job_type': 'Full time', 'posting_url': 'https://example.com/jobs/1',
    'description': 'Build Python and Flask APIs backed by PostgreSQL.',
    'keywords': ['Python', 'Flask'],
}


def test_prefilter_rejects_excluded_jobs_without_ai():
    assert prefilter_job({**JOB, 'title': 'Senior Python Backend Developer'}, PREFERENCES) == (
        False, 'Excluded keyword: senior',
    )
    assert prefilter_job({**JOB, 'company': 'Excluded Corp Ltd'}, PREFERENCES) == (
        False, 'Excluded company: Excluded Corp',
    )
    assert prefilter_job({
        **JOB, 'title': 'Graphic Designer', 'description': 'Design systems.', 'keywords': [],
    }, PREFERENCES)[0] is False


def test_prefiltered_job_uses_no_groq_request():
    class Groq:
        def generate_json(self, *args, **kwargs):
            pytest.fail('pre-filtered job must not use a Groq request')

    result = match_and_draft(
        {**JOB, 'title': 'Senior Python Developer'}, PROFILE, PREFERENCES, Groq(),
        before_request=lambda: pytest.fail('pre-filtered job must not consume daily budget'),
    )

    assert result['score'] == 0
    assert result['prefiltered'] is True
    assert result['draft'] is None


def test_high_match_is_scored_then_drafted_with_profile_only_prompts():
    calls = []

    class Groq:
        def generate_json(self, prompt, before_request=None):
            calls.append(prompt)
            assert before_request()
            if len(calls) == 1:
                return {'score': 88, 'reason': 'Python and Flask match the project work and role.'}
            return {'cover_letter': 'I have built a Flask portfolio.', 'pitch_lines': ['Python', 'Flask', 'APIs']}

    result = match_and_draft(JOB, PROFILE, PREFERENCES, Groq(), before_request=lambda: True)

    assert result['score'] == 88
    assert len(result['draft']['pitch_lines']) == 3
    assert 'only source of facts about the candidate' in calls[1]
    assert 'Never invent' in calls[1]
    assert 'secrets, contact details, or private data' in calls[1]
    assert 'someone@example.com' not in calls[1]


def test_below_threshold_match_is_not_drafted():
    calls = []

    class Groq:
        def generate_json(self, prompt, before_request=None):
            calls.append(prompt)
            return {'score': 69, 'reason': 'Some skill overlap.'}

    result = match_and_draft(JOB, PROFILE, PREFERENCES, Groq())

    assert result['score'] == 69
    assert result['draft'] is None
    assert len(calls) == 1


def test_daily_cap_and_groq_failure_keep_job_unscored():
    class Groq:
        def generate_json(self, *args, **kwargs):
            raise GroqDailyCapReached('cap reached')

    with pytest.raises(GroqDailyCapReached):
        match_and_draft(JOB, PROFILE, PREFERENCES, Groq(), before_request=lambda: False)

    class FailedGroq:
        def generate_json(self, *args, **kwargs):
            raise GroqError('Groq is unavailable')

    with pytest.raises(GroqError, match='unavailable'):
        match_and_draft(JOB, PROFILE, PREFERENCES, FailedGroq())
