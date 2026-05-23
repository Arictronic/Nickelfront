"""add content part extraction metadata

Revision ID: 012_add_content_part_extraction_metadata
Revises: 011
Create Date: 2026-05-23 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "012_add_content_part_extraction_metadata"
down_revision = "011"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    columns = _existing_columns("paper_content_parts")

    if "extraction_method" not in columns:
        op.add_column("paper_content_parts", sa.Column("extraction_method", sa.String(length=80), nullable=True))
    if "extraction_quality_score" not in columns:
        op.add_column("paper_content_parts", sa.Column("extraction_quality_score", sa.Float(), nullable=True))
    if "extraction_warnings" not in columns:
        op.add_column("paper_content_parts", sa.Column("extraction_warnings", sa.JSON(), nullable=True))
    if "extraction_metadata" not in columns:
        op.add_column("paper_content_parts", sa.Column("extraction_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    columns = _existing_columns("paper_content_parts")

    if "extraction_metadata" in columns:
        op.drop_column("paper_content_parts", "extraction_metadata")
    if "extraction_warnings" in columns:
        op.drop_column("paper_content_parts", "extraction_warnings")
    if "extraction_quality_score" in columns:
        op.drop_column("paper_content_parts", "extraction_quality_score")
    if "extraction_method" in columns:
        op.drop_column("paper_content_parts", "extraction_method")
