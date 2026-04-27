"""add_work_type_to_assignments

Revision ID: c060c04e560b
Revises: k6l7m8n9o0p1
Create Date: 2026-04-25 20:11:44.335681

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c060c04e560b'
down_revision = 'k6l7m8n9o0p1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('work_type', sa.String(length=20), nullable=False, server_default='individual'))


def downgrade():
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.drop_column('work_type')
