"""chat sessions + messages — server-side chat persistence, replacing
browser localStorage

Revision ID: chat_sessions
Revises: app_settings
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "chat_sessions"
down_revision = "app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False, server_default="New chat"),
        sa.Column("connection_id", sa.String(32), sa.ForeignKey("connections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
    )

    op.create_table(
        "chat_messages",
        sa.Column("seq", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(32), nullable=False, unique=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("question", sa.Text, nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("ask", sa.JSON, nullable=True),
        sa.Column("feedback", sa.String(8), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
