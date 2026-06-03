"""Add detected language metadata to papers.

Revision ID: 017_add_paper_language
Revises: 017_analysis_results
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa


revision = "017_add_paper_language"
down_revision = "017_analysis_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("language_code", sa.String(length=20), nullable=True))
    op.add_column("papers", sa.Column("language_name", sa.String(length=100), nullable=True))
    op.add_column("papers", sa.Column("language_confidence", sa.Float(), nullable=True))
    op.add_column("papers", sa.Column("language_source", sa.String(length=50), nullable=True))
    op.create_index("ix_papers_language_code", "papers", ["language_code"])


def downgrade() -> None:
    op.drop_index("ix_papers_language_code", table_name="papers")
    op.drop_column("papers", "language_source")
    op.drop_column("papers", "language_confidence")
    op.drop_column("papers", "language_name")
    op.drop_column("papers", "language_code")
