"""add is_finished to assignments

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-04-25

"""
from alembic import op
import sqlalchemy as sa

revision = "k6l7m8n9o0p1"
down_revision = "j5k6l7m8n9o0"
branch_labels = None
depends_on = None


def upgrade():
    # Add the column first (nullable to allow filling existing rows)
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.add_column(sa.Column("is_finished", sa.Boolean(), nullable=True))

    # Fill existing rows
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE assignments SET is_finished = 0 WHERE is_finished IS NULL"))

    # Make it NOT NULL
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.alter_column(
            "is_finished",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        )


def downgrade():
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.drop_column("is_finished")
