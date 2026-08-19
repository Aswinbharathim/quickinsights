"""sql_examples.vote — distinguishes confirmed (thumbs-up) examples used as
few-shot context from rejected (thumbs-down) ones kept only as a "don't
repeat this" signal for retrieval.

Revision ID: sql_example_vote
Revises: chat_sessions
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "sql_example_vote"
down_revision = "chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sql_examples",
        sa.Column("vote", sa.String(8), nullable=False, server_default="up"),
    )


def downgrade() -> None:
    op.drop_column("sql_examples", "vote")
