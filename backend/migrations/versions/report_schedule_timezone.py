"""report_schedules.timezone — fixes a real bug: `time_of_day` ("12:15") had
no timezone concept at all. The backend computed next_run_at treating it as
literal UTC, while the UI's time picker captures the user's local wall-clock
time — so a schedule set for "12:15" would actually fire at 12:15 UTC (e.g.
5:45 PM IST), not 12:15 local as the user intended. Storing an IANA timezone
name per schedule (captured from the browser, default "UTC" for existing
rows) lets compute_next_run/compute_cron_expression interpret time_of_day
correctly via zoneinfo.

Revision ID: report_schedule_timezone
Revises: token_usage_events
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision = "report_schedule_timezone"
down_revision = "token_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_schedules",
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
    )


def downgrade() -> None:
    op.drop_column("report_schedules", "timezone")
