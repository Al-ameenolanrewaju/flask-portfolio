"""Add interview calendar events."""
import sqlalchemy as sa
from alembic import op


revision = 'b72c1d6e3a90'
down_revision = '9a2ce8b7f061'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('job_finder_interviews'):
        op.create_table(
            'job_finder_interviews',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('job_finder_jobs.id', ondelete='CASCADE'), nullable=False),
            sa.Column('uid', sa.String(length=255), nullable=False, unique=True),
            sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('timezone', sa.String(length=100), nullable=False),
            sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default='60'),
            sa.Column('location', sa.String(length=500), nullable=False, server_default=''),
            sa.Column('meeting_url', sa.String(length=1000), nullable=False, server_default=''),
            sa.Column('interviewer', sa.String(length=250), nullable=False, server_default=''),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint('duration_minutes BETWEEN 15 AND 480', name='ck_job_interview_duration'),
        )
        op.create_index('ix_job_finder_interviews_job_start', 'job_finder_interviews', ['job_id', 'starts_at'])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('job_finder_interviews'):
        op.drop_table('job_finder_interviews')