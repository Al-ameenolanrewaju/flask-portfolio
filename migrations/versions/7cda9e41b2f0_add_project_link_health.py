"""Store project demo and repository link health."""
from alembic import op
import sqlalchemy as sa


revision = '7cda9e41b2f0'
down_revision = 'f4b9c8d21a60'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('projects')}
    new_columns = (
        ('demo_link_status', sa.String(length=20)),
        ('demo_link_checked_at', sa.DateTime(timezone=True)),
        ('repo_link_status', sa.String(length=20)),
        ('repo_link_checked_at', sa.DateTime(timezone=True)),
    )
    for name, column_type in new_columns:
        if name not in columns:
            op.add_column('projects', sa.Column(name, column_type, nullable=True))


def downgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('projects')}
    for name in ('repo_link_checked_at', 'repo_link_status', 'demo_link_checked_at', 'demo_link_status'):
        if name in columns:
            op.drop_column('projects', name)