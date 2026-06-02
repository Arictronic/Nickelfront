"""create analysis_results table

Revision ID: 017_analysis_results
Revises: 016_unique_source_record_id
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "017_analysis_results"
down_revision = "016_unique_source_record_id"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not _has_table(inspector, "analysis_results"):
        op.create_table(
            "analysis_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("paper_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("prompt_version", sa.String(length=50), nullable=False, server_default="1.0"),
            sa.Column("context_preview", sa.Text(), nullable=True),
            sa.Column("raw_response", sa.Text(), nullable=True),
            sa.Column("structured_result", postgresql.JSONB(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("analysis_results")}
    if "ix_analysis_results_id" not in existing_indexes:
        op.create_index("ix_analysis_results_id", "analysis_results", ["id"], unique=False)
    if "ix_analysis_results_paper_id" not in existing_indexes:
        op.create_index("ix_analysis_results_paper_id", "analysis_results", ["paper_id"], unique=False)
    if "ix_analysis_results_user_id" not in existing_indexes:
        op.create_index("ix_analysis_results_user_id", "analysis_results", ["user_id"], unique=False)
    if "ix_analysis_results_status" not in existing_indexes:
        op.create_index("ix_analysis_results_status", "analysis_results", ["status"], unique=False)
    if "ix_analysis_results_paper_user" not in existing_indexes:
        op.create_index("ix_analysis_results_paper_user", "analysis_results", ["paper_id", "user_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if _has_table(inspector, "analysis_results"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("analysis_results")}
        for idx_name in ["ix_analysis_results_paper_user", "ix_analysis_results_status",
                          "ix_analysis_results_user_id", "ix_analysis_results_paper_id",
                          "ix_analysis_results_id"]:
            if idx_name in existing_indexes:
                op.drop_index(idx_name, table_name="analysis_results")
        op.drop_table("analysis_results")
