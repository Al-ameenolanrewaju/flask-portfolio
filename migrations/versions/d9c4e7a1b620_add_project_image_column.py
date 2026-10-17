"""Add the project preview image column when absent."""
from alembic import op
import sqlalchemy as sa


revision = 'd9c4e7a1b620'
down_revision = 'c27d98f01a42'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('projects')}
    if 'image' not in columns:
        op.add_column('projects', sa.Column('image', sa.String(length=255), nullable=True))


def downgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('projects')}
    if 'image' in columns:
        op.drop_column('projects', 'image')
