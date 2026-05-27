"""Add canonical patent identifier for cross-source deduplication.

Revision ID: 015_canonical_patent_id
Revises: 014_fulltext_search_vector
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa


revision = "015_canonical_patent_id"
down_revision = "014_fulltext_search_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("canonical_patent_id", sa.String(length=200), nullable=True))
    op.create_index(
        "uq_papers_canonical_patent_id_not_null",
        "papers",
        ["canonical_patent_id"],
        unique=True,
        postgresql_where=sa.text("canonical_patent_id IS NOT NULL"),
        sqlite_where=sa.text("canonical_patent_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_papers_canonical_patent_id_not_null", table_name="papers")
    op.drop_column("papers", "canonical_patent_id")
