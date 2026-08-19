"""app settings — singleton row for AI provider config + SMTP, editable via
the Setup page instead of .env

Revision ID: app_settings
Revises: initial
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "app_settings"
down_revision = "initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("llm_provider", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("openai_api_key_encrypted", sa.Text, nullable=True),
        sa.Column("anthropic_api_key_encrypted", sa.Text, nullable=True),
        sa.Column("openai_chat_model", sa.String(128), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("claude_model", sa.String(128), nullable=False, server_default="claude-sonnet-4-6"),
        sa.Column("embed_provider", sa.String(32), nullable=False, server_default="openai"),
        sa.Column("openai_embed_model", sa.String(128), nullable=False, server_default="text-embedding-3-small"),
        sa.Column("st_embed_model", sa.String(128), nullable=False, server_default="all-MiniLM-L6-v2"),
        sa.Column("embed_dim", sa.Integer, nullable=True),
        sa.Column("hf_token_encrypted", sa.Text, nullable=True),
        sa.Column("smtp_host", sa.String(255), nullable=True),
        sa.Column("smtp_port", sa.Integer, nullable=False, server_default="587"),
        sa.Column("smtp_user", sa.String(255), nullable=True),
        sa.Column("smtp_password_encrypted", sa.Text, nullable=True),
        sa.Column("smtp_from", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
