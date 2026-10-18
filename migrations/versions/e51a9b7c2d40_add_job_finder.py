"""Add private Job Finder preferences, queue, and audit tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e51a9b7c2d40'
down_revision = 'd7a1b93e4f20'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('job_finder_preferences'):
        op.create_table(
            'job_finder_preferences',
            sa.Column('id', sa.SmallInteger(), primary_key=True),
            sa.Column('target_titles', postgresql.JSONB(), nullable=False,
                      server_default=sa.text("'[\"Python Developer\", \"Flask Developer\", \"Backend Developer\", \"Backend Engineer\", \"Junior Backend Developer\"]'::jsonb")),
            sa.Column('keywords', postgresql.JSONB(), nullable=False,
                      server_default=sa.text("'[\"Python\", \"Flask\", \"Django\", \"FastAPI\", \"backend\", \"PostgreSQL\"]'::jsonb")),
            sa.Column('excluded_keywords', postgresql.JSONB(), nullable=False,
                      server_default=sa.text("'[\"senior\", \"staff\", \"principal\", \"lead\", \"manager\", \"director\"]'::jsonb")),
            sa.Column('locations', postgresql.JSONB(), nullable=False,
                      server_default=sa.text("'[\"Worldwide\", \"Lagos, Nigeria\"]'::jsonb")),
            sa.Column('remote_only', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('minimum_match_score', sa.Integer(), nullable=False, server_default='65'),
            sa.Column('excluded_companies', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column('daily_send_cap', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('enabled_sources', postgresql.JSONB(), nullable=False,
                      server_default=sa.text("'[\"remotive\", \"remoteok\"]'::jsonb")),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint('id = 1', name='ck_job_finder_preferences_singleton'),
            sa.CheckConstraint('minimum_match_score BETWEEN 0 AND 100', name='ck_job_finder_score_range'),
            sa.CheckConstraint('daily_send_cap BETWEEN 0 AND 50', name='ck_job_finder_send_cap_range'),
        )

    if not inspector.has_table('job_finder_jobs'):
        op.create_table(
            'job_finder_jobs',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('source_key', sa.String(length=40), nullable=False),
            sa.Column('source_name', sa.String(length=80), nullable=False),
            sa.Column('source_url', sa.Text(), nullable=False),
            sa.Column('external_id', sa.String(length=255), nullable=True),
            sa.Column('posting_url', sa.Text(), nullable=False),
            sa.Column('posting_url_key', sa.Text(), nullable=False),
            sa.Column('apply_url', sa.Text(), nullable=True),
            sa.Column('application_email', sa.String(length=320), nullable=True),
            sa.Column('title', sa.String(length=500), nullable=False),
            sa.Column('title_key', sa.String(length=500), nullable=False),
            sa.Column('company', sa.String(length=300), nullable=False, server_default=''),
            sa.Column('company_key', sa.String(length=300), nullable=False, server_default=''),
            sa.Column('location', sa.String(length=500), nullable=False, server_default=''),
            sa.Column('job_type', sa.String(length=100), nullable=False, server_default=''),
            sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('score', sa.SmallInteger(), nullable=True),
            sa.Column('match_reason', sa.String(length=500), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='found'),
            sa.Column('cover_letter', sa.Text(), nullable=True),
            sa.Column('pitch', sa.Text(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=False, server_default=''),
            sa.Column('follow_up_date', sa.Date(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('scored_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('drafted_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint('score IS NULL OR score BETWEEN 0 AND 100', name='ck_job_finder_job_score_range'),
            sa.CheckConstraint(
                "status IN ('found', 'drafted', 'approved', 'applied', 'interview', 'rejected', 'ignored')",
                name='ck_job_finder_job_status',
            ),
        )
        op.create_index(
            'uq_job_finder_jobs_posting_url', 'job_finder_jobs', ['posting_url_key'], unique=True,
        )
        op.create_index(
            'uq_job_finder_jobs_company_title', 'job_finder_jobs', ['company_key', 'title_key'], unique=True,
        )
        op.create_index('ix_job_finder_jobs_status_score', 'job_finder_jobs', ['status', 'score'])
        op.create_index('ix_job_finder_jobs_follow_up', 'job_finder_jobs', ['follow_up_date', 'status'])
        op.create_index('uq_job_finder_jobs_source_external', 'job_finder_jobs', ['source_key', 'external_id'], unique=True)

    if not inspector.has_table('job_finder_source_runs'):
        op.create_table(
            'job_finder_source_runs',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('source_key', sa.String(length=40), nullable=False),
            sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('succeeded', sa.Boolean(), nullable=False),
            sa.Column('error_code', sa.String(length=80), nullable=True),
        )
        op.create_index('ix_job_finder_source_runs_recent', 'job_finder_source_runs', ['source_key', 'fetched_at'])

    if not inspector.has_table('job_finder_rate_limits'):
        op.create_table(
            'job_finder_rate_limits',
            sa.Column('actor_id', sa.String(length=80), primary_key=True),
            sa.Column('action', sa.String(length=40), primary_key=True),
            sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('request_count', sa.Integer(), nullable=False, server_default='0'),
        )

    if not inspector.has_table('job_finder_send_audit'):
        op.create_table(
            'job_finder_send_audit',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('job_finder_jobs.id', ondelete='CASCADE'), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('recipient', sa.String(length=320), nullable=False),
            sa.Column('subject', sa.String(length=500), nullable=False),
            sa.Column('payload_hash', sa.String(length=64), nullable=False),
            sa.Column('provider_ref', sa.String(length=255), nullable=True),
            sa.Column('error_code', sa.String(length=80), nullable=True),
            sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('sending', 'sent', 'failed')", name='ck_job_finder_send_status'),
        )
        op.create_index('ix_job_finder_send_audit_job', 'job_finder_send_audit', ['job_id', 'attempted_at'])
        op.create_index(
            'uq_job_finder_active_send', 'job_finder_send_audit', ['job_id'], unique=True,
            postgresql_where=sa.text("status IN ('sending', 'sent')"),
        )

    if not inspector.has_table('job_finder_notifications'):
        op.create_table(
            'job_finder_notifications',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('kind', sa.String(length=40), nullable=False),
            sa.Column('scope_key', sa.String(length=120), nullable=False),
            sa.Column('channel', sa.String(length=20), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('error_code', sa.String(length=80), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('kind', 'scope_key', 'channel', name='uq_job_finder_notification_scope'),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    for table in (
        'job_finder_notifications', 'job_finder_send_audit', 'job_finder_rate_limits',
        'job_finder_source_runs', 'job_finder_jobs', 'job_finder_preferences',
    ):
        if inspector.has_table(table):
            op.drop_table(table)
