from results_dashboard import ResultsDashboardService, recommend_minimum_score


def test_recommendation_requires_minimum_sample_and_never_changes_settings():
    rows = [
        {'score_floor': 70, 'applied_count': 9, 'responded_jobs': 6},
        {'score_floor': 80, 'applied_count': 4, 'responded_jobs': 4},
    ]

    assert recommend_minimum_score(rows, minimum_applications=10) == {
        'minimum_match_score': None, 'sample_size': 0, 'response_rate': None, 'score_band': None,
    }
    assert rows[0]['applied_count'] == 9


def test_recommendation_aggregates_score_bands_across_sources():
    rows = [
        {'source_key': 'one', 'score_floor': 70, 'applied_count': 6, 'responded_jobs': 3},
        {'source_key': 'two', 'score_floor': 70, 'applied_count': 5, 'responded_jobs': 4},
        {'source_key': 'one', 'score_floor': 80, 'applied_count': 10, 'responded_jobs': 4},
        {'source_key': 'one', 'score_floor': 90, 'applied_count': 3, 'responded_jobs': 3},
    ]

    suggestion = recommend_minimum_score(rows, minimum_applications=10)

    assert suggestion == {
        'score': 70, 'sample_size': 11, 'response_rate': 100 * 7 / 11,
        'minimum_match_score': 70, 'score_band': '70-79',
    }


def test_dashboard_service_aggregates_rows_without_external_calls():
    class Cursor:
        def __init__(self):
            self.sql = None

        def execute(self, sql):
            self.sql = sql

        def fetchall(self):
            return [{'source_key': 'remotive', 'score_band': '70-79', 'found_count': 12}]

        def close(self):
            pass

    class Connection:
        def __init__(self):
            self.db_cursor = Cursor()
            self.closed = False

        def cursor(self, cursor_factory=None):
            return self.db_cursor

        def close(self):
            self.closed = True

    connection = Connection()
    rows = ResultsDashboardService(lambda: connection).load()

    assert rows == [{'source_key': 'remotive', 'score_band': '70-79', 'found_count': 12}]
    assert 'reply_per_job AS' in connection.db_cursor.sql
    assert 'percentile_cont(0.5)' in connection.db_cursor.sql
    assert connection.closed