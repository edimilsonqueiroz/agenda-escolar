"""add assignment_attachments table

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-04-25

"""
from alembic import op
import sqlalchemy as sa

revision = "i4j5k6l7m8n9"
down_revision = "h3i4j5k6l7m8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assignment_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("file_path", sa.String(255), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assignment_attachments_assignment_id", "assignment_attachments", ["assignment_id"])


def downgrade():
    op.drop_index("ix_assignment_attachments_assignment_id", table_name="assignment_attachments")
    op.drop_table("assignment_attachments")
