"""training_jobs.failed — tracks how many of a job's tables ended in
training_status="failed", so "completed" (all tables processed) can be told
apart from "all tables actually trained successfully".

Revision ID: training_job_failed_count
Revises: sql_example_vote
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "training_job_failed_count"
down_revision = "sql_example_vote"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_jobs",
        sa.Column("failed", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("training_jobs", "failed")
