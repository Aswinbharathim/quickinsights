"""add_module_column — add nullable module column to db_tables and sql_examples tables
for grouping training data by Frappe module.

Revision ID: module_and_business_definitions
Revises: report_schedule_timezone
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "module_and_business_definitions"
down_revision = "report_schedule_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    db_tables_cols = [c["name"] for c in inspector.get_columns("db_tables")]
    if "module" not in db_tables_cols:
        op.add_column("db_tables", sa.Column("module", sa.String(255), nullable=True))

    sql_ex_cols = [c["name"] for c in inspector.get_columns("sql_examples")]
    if "module" not in sql_ex_cols:
        op.add_column("sql_examples", sa.Column("module", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("db_tables", "module")
    op.drop_column("sql_examples", "module")
