"""Add reviewable triage and reply drafts to contact messages."""
import sqlalchemy as sa
from alembic import op


revision = 'c59f8e2d1a70'
down_revision = 'b72c1d6e3a90'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('contact_messages'):
        return
    columns = {column['name'] for column in inspector.get_columns('contact_messages')}
    additions = (
        ('triage_label', sa.String(length=20), False, 'other'),
        ('priority', sa.String(length=10), False, 'normal'),
        ('triage_status', sa.String(length=20), False, 'pending'),
        ('reply_draft', sa.Text(), False, ''),
        ('reply_status', sa.String(length=20), False, 'pending'),
        ('triaged_at', sa.DateTime(timezone=True), True, None),
        ('reply_sent_at', sa.DateTime(timezone=True), True, None),
        ('reply_provider_ref', sa.String(length=255), True, None),
    )
    for name, column_type, nullable, default in additions:
        if name not in columns:
            kwargs = {'nullable': nullable}
            if default is not None:
                if isinstance(default, str):
                    kwargs['server_default'] = sa.text(f"'{default}'")
                else:
                    kwargs['server_default'] = str(default)
            op.add_column('contact_messages', sa.Column(name, column_type, **kwargs))
    known_checks = {item['name'] for item in inspector.get_check_constraints('contact_messages')}
    if 'ck_contact_triage_label' not in known_checks:
        op.create_check_constraint(
            'ck_contact_triage_label', 'contact_messages',
            "triage_label IN ('recruiter', 'client', 'collaboration', 'spam', 'other')",
        )
    if 'ck_contact_priority' not in known_checks:
        op.create_check_constraint(
            'ck_contact_priority', 'contact_messages', "priority IN ('low', 'normal', 'high')",
        )
    if 'ck_contact_reply_status' not in known_checks:
        op.create_check_constraint(
            'ck_contact_reply_status', 'contact_messages',
            "reply_status IN ('pending', 'approved', 'sending', 'sent')",
        )
    if 'ck_contact_triage_status' not in known_checks:
        op.create_check_constraint(
            'ck_contact_triage_status', 'contact_messages',
            "triage_status IN ('pending', 'processing', 'complete', 'failed')",
        )
    op.create_index('ix_contact_triage_review', 'contact_messages', ['triage_status', 'priority', 'created_at'])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('contact_messages'):
        return
    if 'ix_contact_triage_review' in {item['name'] for item in inspector.get_indexes('contact_messages')}:
        op.drop_index('ix_contact_triage_review', table_name='contact_messages')
    constraints = {item['name'] for item in inspector.get_check_constraints('contact_messages')}
    for name in (
        'ck_contact_triage_label', 'ck_contact_priority', 'ck_contact_reply_status',
        'ck_contact_triage_status',
    ):
        if name in constraints:
            op.drop_constraint(name, 'contact_messages', type_='check')
    columns = {column['name'] for column in inspector.get_columns('contact_messages')}
    for name in (
        'reply_provider_ref', 'reply_sent_at', 'triaged_at', 'reply_status', 'reply_draft',
        'triage_status', 'priority', 'triage_label',
    ):
        if name in columns:
            op.drop_column('contact_messages', name)