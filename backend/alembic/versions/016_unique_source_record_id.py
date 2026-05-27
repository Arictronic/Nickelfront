"""Protect source records from concurrent duplicate inserts.

Revision ID: 016_unique_source_record_id
Revises: 015_canonical_patent_id
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa


revision = "016_unique_source_record_id"
down_revision = "015_canonical_patent_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_papers_source_source_id_not_null",
        "papers",
        ["source", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL"),
        sqlite_where=sa.text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_papers_source_source_id_not_null", table_name="papers")
