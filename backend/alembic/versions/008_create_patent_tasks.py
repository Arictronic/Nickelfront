"""create patent_tasks table

Revision ID: 008
Revises: 007
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not _has_table(inspector, "patent_tasks"):
        op.create_table(
            "patent_tasks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("patent_number", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("input_data", sa.JSON(), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("patent_tasks")}
    if "ix_patent_tasks_id" not in existing_indexes:
        op.create_index("ix_patent_tasks_id", "patent_tasks", ["id"], unique=False)
    if "ix_patent_tasks_patent_number" not in existing_indexes:
        op.create_index("ix_patent_tasks_patent_number", "patent_tasks", ["patent_number"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if _has_table(inspector, "patent_tasks"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("patent_tasks")}
        if "ix_patent_tasks_patent_number" in existing_indexes:
            op.drop_index("ix_patent_tasks_patent_number", table_name="patent_tasks")
        if "ix_patent_tasks_id" in existing_indexes:
            op.drop_index("ix_patent_tasks_id", table_name="patent_tasks")
        op.drop_table("patent_tasks")
