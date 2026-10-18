"""Persist project screenshots and monthly API usage."""
from alembic import op
import sqlalchemy as sa


revision = 'a63b9d1e5f20'
down_revision = '7cda9e41b2f0'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('project_screenshots'):
        op.create_table(
            'project_screenshots',
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('image_data', sa.LargeBinary(), nullable=False),
            sa.Column('width', sa.Integer(), nullable=False),
            sa.Column('height', sa.Integer(), nullable=False),
            sa.Column('source', sa.String(length=32), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if not inspector.has_table('screenshot_usage'):
        op.create_table(
            'screenshot_usage',
            sa.Column('month_start', sa.Date(), primary_key=True),
            sa.Column('request_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('quota_exhausted', sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('screenshot_usage'):
        op.drop_table('screenshot_usage')
    if inspector.has_table('project_screenshots'):
        op.drop_table('project_screenshots')