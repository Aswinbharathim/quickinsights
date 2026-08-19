"""master_data_records — new table for imported master/reference-table row
data (e.g. a Category or Status table's real rows), embedded per-connection
into Qdrant so the LLM can resolve a name mentioned in a question to the
actual value/id it maps to in that table.

Import-only, connection-required from the start (no "global" concept ever
existed for this table, unlike sql_examples' history) — mirrors
sql_examples' final (post sql_example_connection_required) shape: required
connection_id FK, ON DELETE CASCADE.

Revision ID: master_data_records
Revises: sql_example_connection_required
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa

revision = "master_data_records"
down_revision = "sql_example_connection_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "master_data_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "connection_id", sa.String(32),
            sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("module", sa.String(255), nullable=True),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("row_data", sa.JSON, nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="excel_import"),
        sa.Column("created_at", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("master_data_records")
