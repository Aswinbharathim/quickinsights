"""sql_example_connection_required — connection_id is no longer optional on
sql_examples: the "global" (connection_id=NULL) example concept has been
removed entirely. Every example, manual or imported, must be tied to one
connection, so:
  - the column becomes NOT NULL
  - the FK's ondelete flips from SET NULL to CASCADE — an orphaned example
    with no connection would violate the NOT NULL constraint, so deleting a
    connection now deletes every example that belonged to it (previously
    only feedback-sourced ones were deleted; manual/imported ones fell back
    to "global" via SET NULL — see routers/connections.py's delete_connection)

Safe to run as-is: as of this migration there are no existing rows with a
NULL connection_id in this deployment (verified against the live DB before
writing this), so no backfill/data-loss decision was needed. If a future
deployment somehow has legacy NULL rows, this migration will fail loudly at
the NOT NULL step rather than silently dropping data — resolve those rows
manually (delete or assign a connection) before re-running.

Revision ID: sql_example_connection_required
Revises: sql_example_source_message
Create Date: 2026-08-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "sql_example_connection_required"
down_revision = "sql_example_source_message"
branch_labels = None
depends_on = None


def _existing_connection_id_fk(inspector):
    """Return the actual name of the FK on sql_examples.connection_id -> connections,
    if one exists under any name. Deployments that had the column added out-of-band
    (or whose schema was ever bootstrapped from the ORM models instead of Alembic) can
    end up with this constraint auto-named by MySQL instead of `fk_sql_examples_connection_id`,
    or missing altogether — so look it up by column rather than assuming the name."""
    for fk in inspector.get_foreign_keys("sql_examples"):
        if fk.get("constrained_columns") == ["connection_id"]:
            return fk.get("name")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_fk = _existing_connection_id_fk(inspector)
    if existing_fk:
        op.drop_constraint(existing_fk, "sql_examples", type_="foreignkey")
    op.alter_column("sql_examples", "connection_id", existing_type=sa.String(32), nullable=False)
    op.create_foreign_key(
        "fk_sql_examples_connection_id",
        "sql_examples",
        "connections",
        ["connection_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_fk = _existing_connection_id_fk(inspector)
    if existing_fk:
        op.drop_constraint(existing_fk, "sql_examples", type_="foreignkey")
    op.alter_column("sql_examples", "connection_id", existing_type=sa.String(32), nullable=True)
    op.create_foreign_key(
        "fk_sql_examples_connection_id",
        "sql_examples",
        "connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
