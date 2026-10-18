from psycopg2.extras import RealDictCursor

RESULTS_QUERY = """
WITH reply_per_job AS (
    SELECT job_id,
           COUNT(*) FILTER (WHERE category NOT IN ('auto_reply', 'unrelated')) AS reply_count,
           MIN(received_at) FILTER (WHERE category NOT IN ('auto_reply', 'unrelated')) AS first_reply
    FROM job_finder_replies
    WHERE job_id IS NOT NULL
    GROUP BY job_id
), sent_per_job AS (
    SELECT job_id, MIN(sent_at) AS first_sent
    FROM job_finder_send_audit
    WHERE status='sent' AND sent_at IS NOT NULL
    GROUP BY job_id
)
SELECT j.source_key,
       CASE WHEN j.score IS NULL THEN 'unscored'
            WHEN j.score < 70 THEN '0-69'
            WHEN j.score < 80 THEN '70-79'
            WHEN j.score < 90 THEN '80-89'
            ELSE '90+'
       END AS score_band,
       CASE WHEN j.score IS NULL THEN NULL
            WHEN j.score < 70 THEN 0
            WHEN j.score < 80 THEN 70
            WHEN j.score < 90 THEN 80
            ELSE 90
       END AS score_floor,
       COUNT(*) AS found_count,
       COUNT(*) FILTER (
           WHERE j.status IN ('applied', 'responded', 'interview', 'offer', 'rejected')
              OR sent.job_id IS NOT NULL
       ) AS applied_count,
       COALESCE(SUM(reply.reply_count), 0) AS replies_count,
       COUNT(*) FILTER (WHERE COALESCE(reply.reply_count, 0) > 0) AS responded_jobs,
       COUNT(*) FILTER (WHERE j.status='interview') AS interviews_count,
       COUNT(*) FILTER (WHERE j.status='rejected') AS rejections_count,
       CASE WHEN COUNT(*) FILTER (
           WHERE j.status IN ('applied', 'responded', 'interview', 'offer', 'rejected')
              OR sent.job_id IS NOT NULL
       ) = 0 THEN NULL
       ELSE ROUND(
           100.0 * COUNT(*) FILTER (WHERE COALESCE(reply.reply_count, 0) > 0)
           / COUNT(*) FILTER (
               WHERE j.status IN ('applied', 'responded', 'interview', 'offer', 'rejected')
                  OR sent.job_id IS NOT NULL
           ), 1
       ) END AS response_rate,
       percentile_cont(0.5) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM (reply.first_reply - sent.first_sent)) / 86400.0
       ) FILTER (WHERE reply.first_reply IS NOT NULL AND sent.first_sent IS NOT NULL) AS median_days_to_reply,
       COUNT(*) FILTER (WHERE reply.first_reply IS NOT NULL AND sent.first_sent IS NOT NULL) AS reply_sample_count
FROM job_finder_jobs j
LEFT JOIN reply_per_job reply ON reply.job_id=j.id
LEFT JOIN sent_per_job sent ON sent.job_id=j.id
GROUP BY j.source_key, score_band, score_floor
ORDER BY j.source_key, score_floor NULLS LAST
"""


def recommend_minimum_score(rows, minimum_applications=10):
    by_floor = {}
    for row in rows:
        floor = row.get('score_floor')
        if floor is None or floor < 70:
            continue
        aggregate = by_floor.setdefault(floor, {'applied': 0, 'responded': 0})
        aggregate['applied'] += int(row.get('applied_count') or 0)
        aggregate['responded'] += int(row.get('responded_jobs') or 0)

    eligible = [
        {
            'score': floor,
            'sample_size': values['applied'],
            'response_rate': values['responded'] / values['applied'] * 100,
        }
        for floor, values in by_floor.items()
        if values['applied'] >= minimum_applications and values['applied'] > 0
    ]
    if not eligible:
        return {'minimum_match_score': None, 'sample_size': 0, 'response_rate': None, 'score_band': None}
    best = max(eligible, key=lambda item: (item['response_rate'], item['score']))
    score_band = f"{best['score']}-79" if best['score'] == 70 else (
        f"{best['score']}-89" if best['score'] == 80 else '90+'
    )
    return {**best, 'minimum_match_score': best['score'], 'score_band': score_band}


class ResultsDashboardService:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def load(self):
        connection = self.connection_factory()
        cursor = None
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(RESULTS_QUERY)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()
            connection.close()