"""add_psychologist_availabilities

Revision ID: c1b2d3e4f5a6
Revises: 8a7b6c5d4e3f
Create Date: 2026-04-24 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1b2d3e4f5a6"
down_revision = "8a7b6c5d4e3f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "psychologist_availabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("psychologist_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["psychologist_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("psychologist_id", "weekday", name="uq_psychologist_weekday"),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_availability_weekday_range"),
    )
    op.create_index(
        op.f("ix_psychologist_availabilities_psychologist_id"),
        "psychologist_availabilities",
        ["psychologist_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_psychologist_availabilities_psychologist_id"), table_name="psychologist_availabilities")
    op.drop_table("psychologist_availabilities")
