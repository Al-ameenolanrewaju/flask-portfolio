"""Add cached interview company briefings."""
import sqlalchemy as sa
from alembic import op


revision = 'da8f0c2b1e64'
down_revision = 'c59f8e2d1a70'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('job_finder_briefings'):
        op.create_table(
            'job_finder_briefings',
            sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('job_finder_jobs.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('briefing_json', sa.Text(), nullable=False),
            sa.Column('sources_json', sa.Text(), nullable=False),
            sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('job_finder_briefings'):
        op.drop_table('job_finder_briefings')