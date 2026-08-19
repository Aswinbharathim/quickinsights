"""initial schema — connections, db_tables, sql_examples, reports,
report_schedules, schedule_runs, training_jobs, discovery_progress

Revision ID: initial
Revises:
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("db_type", sa.String(32), nullable=False, server_default="mariadb"),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer, nullable=False, server_default="3306"),
        sa.Column("database_name", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_encrypted", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="untested"),
        sa.Column("last_tested_at", sa.String(64), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
    )

    op.create_table(
        "sql_examples",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sql", sa.Text, nullable=False),
        sa.Column("tags", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
    )

    op.create_table(
        "db_tables",
        sa.Column("connection_id", sa.String(32), sa.ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("table_name", sa.String(255), primary_key=True),
        sa.Column("doctype", sa.String(255), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("primary_key", sa.String(255), nullable=True, server_default="name"),
        sa.Column("is_child_table", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("parent_table", sa.String(255), nullable=True),
        sa.Column("foreign_keys", sa.JSON, nullable=False),
        sa.Column("columns", sa.JSON, nullable=False),
        sa.Column("training_status", sa.String(32), nullable=False, server_default="untrained"),
        sa.Column("trained_at", sa.String(64), nullable=True),
        sa.Column("vector_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("training_error", sa.Text, nullable=True),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("sql", sa.Text, nullable=False),
        sa.Column("columns", sa.JSON, nullable=False),
        sa.Column("rows", sa.JSON, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("connection_id", sa.String(32), sa.ForeignKey("connections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
    )

    op.create_table(
        "report_schedules",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("report_id", sa.String(32), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False, server_default="daily"),
        sa.Column("time_of_day", sa.String(8), nullable=False, server_default="09:00"),
        sa.Column("day_of_week", sa.Integer, nullable=True),
        sa.Column("day_of_month", sa.Integer, nullable=True),
        sa.Column("recipient_group", sa.String(255), nullable=True),
        sa.Column("recipient_emails", sa.JSON, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("cron_expression", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("last_run_at", sa.String(64), nullable=True),
        sa.Column("next_run_at", sa.String(64), nullable=True),
    )

    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schedule_id", sa.String(32), sa.ForeignKey("report_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.String(32), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.String(64), nullable=True),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("recipients", sa.JSON, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
    )

    op.create_table(
        "training_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("connection_id", sa.String(32), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_names", sa.JSON, nullable=False),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.String(64), nullable=True),
    )

    op.create_table(
        "discovery_progress",
        sa.Column("connection_id", sa.String(32), sa.ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="idle"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.String(64), nullable=True),
        sa.Column("table_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("discovery_progress")
    op.drop_table("training_jobs")
    op.drop_table("schedule_runs")
    op.drop_table("report_schedules")
    op.drop_table("reports")
    op.drop_table("db_tables")
    op.drop_table("sql_examples")
    op.drop_table("connections")
