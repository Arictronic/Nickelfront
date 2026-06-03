"""Add content typing metadata to paper_content_parts.

Revision ID: 013_add_content_part_types
Revises: 012_content_extract_meta
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa


revision = "013_add_content_part_types"
down_revision = "012_content_extract_meta"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _existing_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    columns = _existing_columns("paper_content_parts")
    if "content_type" not in columns:
        op.add_column("paper_content_parts", sa.Column("content_type", sa.String(length=30), nullable=True))
        op.execute("UPDATE paper_content_parts SET content_type = 'body' WHERE content_type IS NULL")
        op.alter_column("paper_content_parts", "content_type", nullable=False)
    if "section_title" not in columns:
        op.add_column("paper_content_parts", sa.Column("section_title", sa.String(length=500), nullable=True))
    if "section_index" not in columns:
        op.add_column("paper_content_parts", sa.Column("section_index", sa.Integer(), nullable=True))
    if "page_profile" not in columns:
        op.add_column("paper_content_parts", sa.Column("page_profile", sa.String(length=80), nullable=True))
    if "include_in_embedding" not in columns:
        op.add_column("paper_content_parts", sa.Column("include_in_embedding", sa.Boolean(), nullable=True))
        op.execute("UPDATE paper_content_parts SET include_in_embedding = TRUE WHERE include_in_embedding IS NULL")
        op.alter_column("paper_content_parts", "include_in_embedding", nullable=False)

    indexes = _existing_indexes("paper_content_parts")
    if "ix_paper_content_parts_content_type" not in indexes:
        op.create_index("ix_paper_content_parts_content_type", "paper_content_parts", ["content_type"], unique=False)
    if "ix_paper_content_parts_include_in_embedding" not in indexes:
        op.create_index("ix_paper_content_parts_include_in_embedding", "paper_content_parts", ["include_in_embedding"], unique=False)
    if "ix_paper_content_parts_paper_type" not in indexes:
        op.create_index("ix_paper_content_parts_paper_type", "paper_content_parts", ["paper_id", "content_type"], unique=False)
    if "ix_paper_content_parts_paper_embedding" not in indexes:
        op.create_index("ix_paper_content_parts_paper_embedding", "paper_content_parts", ["paper_id", "include_in_embedding"], unique=False)


def downgrade() -> None:
    indexes = _existing_indexes("paper_content_parts")
    for name in [
        "ix_paper_content_parts_paper_embedding",
        "ix_paper_content_parts_paper_type",
        "ix_paper_content_parts_include_in_embedding",
        "ix_paper_content_parts_content_type",
    ]:
        if name in indexes:
            op.drop_index(name, table_name="paper_content_parts")

    columns = _existing_columns("paper_content_parts")
    for name in ["include_in_embedding", "page_profile", "section_index", "section_title", "content_type"]:
        if name in columns:
            op.drop_column("paper_content_parts", name)
