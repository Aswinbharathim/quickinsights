"""token_usage_events — project-wide token/cost tracking: one row per
LLM/embedding call (chat, run-sql summaries, suggested questions, and every
training embedding), so usage can be queried/aggregated instead of only
existing as an opaque per-message JSON blob.

Revision ID: token_usage_events
Revises: training_job_failed_count
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = "token_usage_events"
down_revision = "training_job_failed_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_usage_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("connection_id", sa.String(32), nullable=True),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("ix_token_usage_events_connection_id", "token_usage_events", ["connection_id"])
    op.create_index("ix_token_usage_events_operation", "token_usage_events", ["operation"])
    op.create_index("ix_token_usage_events_created_at", "token_usage_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("token_usage_events")
