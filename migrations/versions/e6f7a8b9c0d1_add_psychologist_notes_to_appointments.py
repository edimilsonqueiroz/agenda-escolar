"""add_psychologist_notes_to_appointments

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-04-24 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e6f7a8b9c0d1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("appointments", sa.Column("psychologist_notes", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("appointments", "psychologist_notes")
