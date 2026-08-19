"""sql_example_source_message — add nullable source_message_id FK to
sql_examples, linking a feedback-sourced example back to the chat message it
came from, so deleting the example can also clear that message's feedback
icon back to neutral instead of leaving it stuck "voted" with nothing left
backing it up.

Revision ID: sql_example_source_message
Revises: sql_example_connection_id
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "sql_example_source_message"
down_revision = "sql_example_connection_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("sql_examples")]
    if "source_message_id" not in cols:
        op.add_column("sql_examples", sa.Column("source_message_id", sa.String(32), nullable=True))
        op.create_foreign_key(
            "fk_sql_examples_source_message_id",
            "sql_examples",
            "chat_messages",
            ["source_message_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_sql_examples_source_message_id", "sql_examples", type_="foreignkey")
    op.drop_column("sql_examples", "source_message_id")
