"""Store pending Groq project drafts and daily request usage."""
from alembic import op
import sqlalchemy as sa


revision = 'd7a1b93e4f20'
down_revision = 'a63b9d1e5f20'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('project_ai_drafts'):
        op.create_table(
            'project_ai_drafts',
            sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('readme_hash', sa.String(length=64), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('case_study_problem', sa.Text(), nullable=False),
            sa.Column('case_study_built', sa.Text(), nullable=False),
            sa.Column('case_study_result', sa.Text(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if not inspector.has_table('groq_usage'):
        op.create_table(
            'groq_usage',
            sa.Column('usage_date', sa.Date(), primary_key=True),
            sa.Column('request_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('quota_alerted', sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('groq_usage'):
        op.drop_table('groq_usage')
    if inspector.has_table('project_ai_drafts'):
        op.drop_table('project_ai_drafts')
