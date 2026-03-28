"""add paper ai/pdf enrichment fields

Revision ID: 007
Revises: 006
Create Date: 2026-03-28
"""

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns_to_add = [
        ("pdf_url", sa.String(length=1000), True),
        ("pdf_local_path", sa.String(length=1000), True),
        ("content_task_id", sa.String(length=100), True),
        ("processing_error", sa.Text(), True),
        ("summary_ru", sa.Text(), True),
        ("analysis_ru", sa.Text(), True),
        ("translation_ru", sa.Text(), True),
    ]

    for name, col_type, nullable in columns_to_add:
        if not _has_column(inspector, "papers", name):
            op.add_column("papers", sa.Column(name, col_type, nullable=nullable))

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("papers")}
    if "ix_papers_content_task_id" not in existing_indexes:
        op.create_index("ix_papers_content_task_id", "papers", ["content_task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_papers_content_task_id", table_name="papers")
    op.drop_column("papers", "translation_ru")
    op.drop_column("papers", "analysis_ru")
    op.drop_column("papers", "summary_ru")
    op.drop_column("papers", "processing_error")
    op.drop_column("papers", "content_task_id")
    op.drop_column("papers", "pdf_local_path")
    op.drop_column("papers", "pdf_url")
