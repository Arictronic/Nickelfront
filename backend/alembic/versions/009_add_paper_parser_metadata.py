"""add parser metadata fields to papers

Revision ID: 009
Revises: 008
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    columns_to_add = [
        ("parse_confidence", sa.Float(), True),
        ("provenance", sa.JSON(), False, sa.text("'{}'")),
        ("quality_flags", sa.JSON(), False, sa.text("'[]'")),
        ("schema_version", sa.String(length=20), True),
    ]

    for item in columns_to_add:
        name = item[0]
        col_type = item[1]
        nullable = item[2]
        server_default = item[3] if len(item) > 3 else None
        if not _has_column(inspector, "papers", name):
            op.add_column(
                "papers",
                sa.Column(name, col_type, nullable=nullable, server_default=server_default),
            )

    if _has_column(inspector, "papers", "schema_version"):
        op.execute("UPDATE papers SET schema_version = '2.0' WHERE schema_version IS NULL")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for column_name in ("schema_version", "quality_flags", "provenance", "parse_confidence"):
        if _has_column(inspector, "papers", column_name):
            op.drop_column("papers", column_name)
