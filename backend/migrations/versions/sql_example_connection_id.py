"""sql_example_connection_id — add nullable connection_id FK to sql_examples,
so few-shot examples can be scoped to the connection they were written
against instead of being retrieved across every connection.

A pre-existing example with connection_id=NULL is treated as a "global"
example that still applies everywhere (see rag.py's build_context) — this
migration doesn't backfill anything, it just adds the column.

Revision ID: sql_example_connection_id
Revises: module_and_business_definitions
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "sql_example_connection_id"
down_revision = "module_and_business_definitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("sql_examples")]
    if "connection_id" not in cols:
        op.add_column("sql_examples", sa.Column("connection_id", sa.String(32), nullable=True))
    has_fk = any(
        fk.get("constrained_columns") == ["connection_id"]
        for fk in inspector.get_foreign_keys("sql_examples")
    )
    if not has_fk:
        op.create_foreign_key(
            "fk_sql_examples_connection_id",
            "sql_examples",
            "connections",
            ["connection_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    has_fk = any(
        fk.get("constrained_columns") == ["connection_id"]
        for fk in inspector.get_foreign_keys("sql_examples")
    )
    if has_fk:
        op.drop_constraint("fk_sql_examples_connection_id", "sql_examples", type_="foreignkey")
    op.drop_column("sql_examples", "connection_id")
