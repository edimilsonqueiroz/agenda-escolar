"""add_subject_attachment_to_assignments

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-04-25 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assignments", sa.Column("subject", sa.String(100), nullable=True))
    op.add_column("assignments", sa.Column("attachment_path", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("assignments", "attachment_path")
    op.drop_column("assignments", "subject")
