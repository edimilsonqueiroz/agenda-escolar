"""add_period_to_psychologist_availabilities

Revision ID: d4e5f6a7b8c9
Revises: c1b2d3e4f5a6
Create Date: 2026-04-24 21:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c1b2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "psychologist_availabilities",
        sa.Column("period", sa.String(length=10), nullable=True, server_default="manha"),
    )

    op.execute("UPDATE psychologist_availabilities SET period = 'manha' WHERE period IS NULL")

    with op.batch_alter_table("psychologist_availabilities") as batch_op:
        batch_op.drop_constraint("uq_psychologist_weekday", type_="unique")
        batch_op.alter_column("period", existing_type=sa.String(length=10), nullable=False, server_default=None)
        batch_op.create_unique_constraint(
            "uq_psychologist_weekday_period",
            ["psychologist_id", "weekday", "period"],
        )


def downgrade():
    with op.batch_alter_table("psychologist_availabilities") as batch_op:
        batch_op.drop_constraint("uq_psychologist_weekday_period", type_="unique")
        batch_op.create_unique_constraint("uq_psychologist_weekday", ["psychologist_id", "weekday"])

    op.drop_column("psychologist_availabilities", "period")
