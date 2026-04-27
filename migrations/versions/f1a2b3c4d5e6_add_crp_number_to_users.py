"""add_crp_number_to_users

Revision ID: f1a2b3c4d5e6
Revises: e6f7a8b9c0d1
Create Date: 2026-04-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "cb7655c35d90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("crp_number", sa.String(30), nullable=True))


def downgrade():
    op.drop_column("users", "crp_number")
