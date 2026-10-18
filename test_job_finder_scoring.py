from groq_client import GroqDailyCapReached, GroqError
from job_finder_service import DEFAULT_PREFERENCES, JobFinderService

JOB_ROW = {
    'id': 7, 'posting_url_key': 'https://example.com/job/7', 'title': 'Python Flask Developer',
    'company': 'Example', 'company_key': 'example', 'location': 'Worldwide',
}
SOURCE_JOB = {
    **JOB_ROW,
    'posting_url': JOB_ROW['posting_url_key'], 'description': 'Build Python and Flask APIs.',
    'keywords': ['Python', 'Flask'], 'job_type': 'full time', 'source_name': 'Remotive',
    'source_url': 'https://remotive.com/remote-jobs/api', 'apply_url': JOB_ROW['posting_url_key'],
}
PROFILE = {
    'name': 'Al-ameen Olanrewaju', 'about': 'Builds Flask projects.',
    'skills': {'Backend': ['Python', 'Flask']},
    'projects': [{'title': 'Portfolio', 'description': 'A Flask app.', 'technologies': ['Python', 'Flask']}],
    'synced_repositories': [{'name': 'owner/repo', 'description': 'Flask APIs'}],
    'cv_text': 'Public About, Skills, and project information only.',
}


def _service(monkeypatch):
    service = JobFinderService(connection_factory=lambda: None, sources={})
    monkeypatch.setattr(service, 'get_preferences', lambda: DEFAULT_PREFERENCES)
    monkeypatch.setattr(service, '_unscored_jobs_for_urls', lambda keys: [JOB_ROW])
    saved = []
    monkeypatch.setattr(service, '_save_match', lambda *args: saved.append(args))
    monkeypatch.setattr(service, 'groq_request_guard', lambda: True)
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    return service, saved


def test_scoring_drafts_only_high_matches_and_uses_public_profile():
    job = {**SOURCE_JOB, 'id': 7, 'status': 'found', 'score': None}
    prompts = []
    saved = []

    class Groq:
        def generate_json(self, prompt, before_request=None):
            prompts.append(prompt)
            assert before_request()
            if len(prompts) == 1:
                return {'score': 90, 'reason': 'Python and Flask fit the profile.'}
            return {'cover_letter': 'I have built a Flask portfolio.', 'pitch_lines': ['Python', 'Flask', 'Public project']}

    service = JobFinderService(connection_factory=lambda: None, sources={}, groq_client_factory=lambda *args: Groq())
    service.get_preferences = lambda: DEFAULT_PREFERENCES
    service.groq_request_guard = lambda: True
    service._unscored_jobs_for_urls = lambda keys: [job]
    service._save_match = lambda *args: saved.append(args)

    result = service.score_new_jobs([SOURCE_JOB], profile=PROFILE)

    assert result == {'scored': 1, 'drafted': 1, 'unscored': 0, 'failures': 0}
    assert saved[0][0:3] == (7, 90, 'Python and Flask fit the profile.')
    assert saved[0][3]['pitch_lines'] == ['Python', 'Flask', 'Public project']
    assert 'Public About, Skills' in prompts[0]
    assert 'CONTACT_EMAIL' not in prompts[0]
    assert 'someone@example.com' not in prompts[1]
    assert 'Never invent' in prompts[1]


def test_below_threshold_job_is_scored_but_not_drafted(monkeypatch):
    service, saved = _service(monkeypatch)
    preferences = {**DEFAULT_PREFERENCES, 'minimum_match_score': 70}
    calls = []

    class Groq:
        def generate_json(self, prompt, before_request=None):
            calls.append(prompt)
            return {'score': 69, 'reason': 'Some matching skills.'}

    service.groq_client_factory = lambda *args: Groq()
    result = service.score_new_jobs([SOURCE_JOB], preferences=preferences, profile=PROFILE)

    assert result == {'scored': 1, 'drafted': 0, 'unscored': 0, 'failures': 0}
    assert len(calls) == 1
    assert saved[0][3] is None


def test_daily_cap_and_groq_failure_keep_job_unscored(monkeypatch):
    service, saved = _service(monkeypatch)

    class CappedGroq:
        def generate_json(self, *args, **kwargs):
            raise GroqDailyCapReached('cap')

    service.groq_client_factory = lambda *args: CappedGroq()
    result = service.score_new_jobs([SOURCE_JOB], profile=PROFILE)
    assert result['unscored'] == 1
    assert saved == []

    class FailedGroq:
        def generate_json(self, *args, **kwargs):
            raise GroqError('Groq down')

    service.groq_client_factory = lambda *args: FailedGroq()
    result = service.score_new_jobs([SOURCE_JOB], profile=PROFILE)
    assert result['unscored'] == 1
    assert result['failures'] == 1
    assert saved == []