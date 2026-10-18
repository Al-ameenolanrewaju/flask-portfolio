"""Add privacy-limited inbox reply tracking."""

import sqlalchemy as sa
from alembic import op

revision = '9a2ce8b7f061'
down_revision = 'e51a9b7c2d40'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('job_finder_jobs'):
        constraints = {item['name'] for item in inspector.get_check_constraints('job_finder_jobs')}
        if 'ck_job_finder_job_status' in constraints:
            op.drop_constraint('ck_job_finder_job_status', 'job_finder_jobs', type_='check')
        op.create_check_constraint(
            'ck_job_finder_job_status',
            'job_finder_jobs',
            "status IN ('found', 'drafted', 'approved', 'applied', 'responded', 'interview', 'offer', 'rejected', 'ignored')",
        )

    if not inspector.has_table('job_finder_replies'):
        op.create_table(
            'job_finder_replies',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('message_id', sa.String(length=500), nullable=False, unique=True),
            sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('job_finder_jobs.id', ondelete='SET NULL'), nullable=True),
            sa.Column('email_from', sa.String(length=320), nullable=False, server_default=''),
            sa.Column('subject', sa.String(length=500), nullable=False, server_default=''),
            sa.Column('excerpt', sa.String(length=360), nullable=True),
            sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('category', sa.String(length=32), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=False),
            sa.Column('match_strategy', sa.String(length=40), nullable=False),
            sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('status_before', sa.String(length=20), nullable=True),
            sa.Column('status_after', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "category IN ('interview_invite', 'rejection', 'request_for_info', 'offer', 'auto_reply', 'unrelated')",
                name='ck_job_finder_reply_category',
            ),
            sa.CheckConstraint('confidence BETWEEN 0 AND 1', name='ck_job_finder_reply_confidence'),
        )
        op.create_index('ix_job_finder_replies_review', 'job_finder_replies', ['needs_review', 'received_at'])
        op.create_index('ix_job_finder_replies_job', 'job_finder_replies', ['job_id', 'received_at'])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('job_finder_replies'):
        op.drop_table('job_finder_replies')
    if inspector.has_table('job_finder_jobs'):
        constraints = {item['name'] for item in inspector.get_check_constraints('job_finder_jobs')}
        if 'ck_job_finder_job_status' in constraints:
            op.drop_constraint('ck_job_finder_job_status', 'job_finder_jobs', type_='check')
        op.create_check_constraint(
            'ck_job_finder_job_status',
            'job_finder_jobs',
            "status IN ('found', 'drafted', 'approved', 'applied', 'interview', 'rejected', 'ignored')",
        )