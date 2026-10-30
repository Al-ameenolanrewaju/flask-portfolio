"""Add default values for contact_messages columns."""
import sqlalchemy as sa
from alembic import op


revision = 'e6f7a8b9c0d1'
down_revision = 'da8f0c2b1e64'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('contact_messages'):
        return
    columns = {column['name'] for column in inspector.get_columns('contact_messages')}
    with op.batch_alter_table('contact_messages', schema=None) as batch_op:
        if 'is_read' in columns:
            batch_op.alter_column('is_read', server_default=sa.text('false'))
        if 'is_replied' in columns:
            batch_op.alter_column('is_replied', server_default=sa.text('false'))
        if 'updated_at' in columns:
            batch_op.alter_column('updated_at', server_default=sa.func.now())


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('contact_messages'):
        return
    with op.batch_alter_table('contact_messages', schema=None) as batch_op:
        batch_op.alter_column('is_read', server_default=None)
        batch_op.alter_column('is_replied', server_default=None)
        batch_op.alter_column('updated_at', server_default=None)

