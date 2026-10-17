"""Add GitHub synchronization and display controls to projects."""
from alembic import op
import sqlalchemy as sa


revision = 'c27d98f01a42'
down_revision = 'a1c2b3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table('projects'):
        op.create_table(
            'projects',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title', sa.String(length=150), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('link', sa.String(length=255), nullable=True),
            sa.Column('image', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )
    op.add_column('projects', sa.Column('github_repo_id', sa.BigInteger(), nullable=True))
    op.add_column('projects', sa.Column('github_full_name', sa.String(length=255), nullable=True))
    op.add_column('projects', sa.Column('languages', sa.Text(), nullable=False, server_default='[]'))
    op.add_column('projects', sa.Column('topics', sa.Text(), nullable=False, server_default='[]'))
    op.add_column('projects', sa.Column('stars', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('projects', sa.Column('last_pushed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('projects', sa.Column('edited_fields', sa.Text(), nullable=False, server_default='[]'))
    op.add_column('projects', sa.Column('is_visible', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('projects', sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('projects', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('projects', sa.Column('github_missing', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('projects', sa.Column('github_archived', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('projects', sa.Column('homepage_url', sa.String(length=255), nullable=True))
    op.create_index('ix_projects_github_repo_id', 'projects', ['github_repo_id'], unique=True)


def downgrade():
    op.drop_index('ix_projects_github_repo_id', table_name='projects')
    for column in (
        'homepage_url', 'github_archived', 'github_missing', 'sort_order', 'is_pinned', 'is_visible',
        'edited_fields', 'last_pushed_at', 'stars', 'topics', 'languages',
        'github_full_name', 'github_repo_id',
    ):
        op.drop_column('projects', column)