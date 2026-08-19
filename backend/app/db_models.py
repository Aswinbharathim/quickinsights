"""SQLAlchemy ORM tables backing app/store.py — one table per in-memory
store QuickInsights used to keep only in RAM (see store.py's module
docstring history). Lives in the metadata database (app/database.py),
never in a user's connected database."""
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConnectionRow(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    db_type: Mapped[str] = mapped_column(String(32), default="mariadb")
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=3306)
    database_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="untested")
    last_tested_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))


class DbTableRow(Base):
    __tablename__ = "db_tables"

    connection_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True
    )
    table_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    doctype: Mapped[str] = mapped_column(String(255))
    module: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_key: Mapped[str | None] = mapped_column(String(255), default="name")
    is_child_table: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_table: Mapped[str | None] = mapped_column(String(255), nullable=True)
    foreign_keys: Mapped[list] = mapped_column(JSON, default=list)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    training_status: Mapped[str] = mapped_column(String(32), default="untrained")
    trained_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vector_count: Mapped[int] = mapped_column(Integer, default=0)
    training_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SqlExampleRow(Base):
    __tablename__ = "sql_examples"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str] = mapped_column(Text)
    module: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Required — no more "global" examples; every one belongs to exactly one
    # connection (see rag.py's build_context / train_sql_example_now).
    # CASCADE on delete: an example can't be orphaned to NULL anymore, so
    # deleting a connection deletes every example that belonged to it (see
    # routers/connections.py's delete_connection).
    connection_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    )
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), default="manual")
    vote: Mapped[str] = mapped_column(String(8), default="up")
    # Only set for source="feedback" rows — see SqlExample's docstring on
    # this field in models.py. SET NULL rather than CASCADE: deleting the
    # chat message shouldn't delete a confirmed training example, just sever
    # the (already one-way, cosmetic) link back to it.
    source_message_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )


class MasterDataRecordRow(Base):
    __tablename__ = "master_data_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Required, CASCADE — same rule as SqlExampleRow.connection_id: a master
    # data row can't be orphaned to "global", so it dies with its connection.
    connection_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    )
    module: Mapped[str | None] = mapped_column(String(255), nullable=True)
    table_name: Mapped[str] = mapped_column(String(255))
    # Arbitrary column -> value pairs from the uploaded file's header row —
    # every master table has different columns, so there's no fixed schema.
    row_data: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="excel_import")
    created_at: Mapped[str] = mapped_column(String(64))


class ReportRow(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    sql: Mapped[str] = mapped_column(Text)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    rows: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    connection_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(64))


class ReportScheduleRow(Base):
    __tablename__ = "report_schedules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(32), ForeignKey("reports.id", ondelete="CASCADE"))
    frequency: Mapped[str] = mapped_column(String(16), default="daily")
    time_of_day: Mapped[str] = mapped_column(String(8), default="09:00")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recipient_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_emails: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cron_expression: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64))
    last_run_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_run_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ScheduleRunRow(Base):
    __tablename__ = "schedule_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    schedule_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("report_schedules.id", ondelete="CASCADE")
    )
    report_id: Mapped[str] = mapped_column(String(32), ForeignKey("reports.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TrainingJobRow(Base):
    __tablename__ = "training_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    connection_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("connections.id", ondelete="CASCADE")
    )
    table_names: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DiscoveryProgressRow(Base):
    __tablename__ = "discovery_progress"

    connection_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), default="idle")
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChatSessionRow(Base):
    """A chat conversation — was previously kept only in the browser's
    localStorage (zustand persist); now server-side so it survives clearing
    site data / switching browsers/devices."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    connection_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("connections.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(64))


class ChatMessageRow(Base):
    """One message in a chat session. `seq` (not `id`) is the primary key so
    ordering within a session is a simple, always-correct auto-increment —
    `id` is the client-generated id used for optimistic UI updates before the
    message is persisted."""

    __tablename__ = "chat_messages"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))
    ask: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(8), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppSettingsRow(Base):
    """Singleton row (id is always 1) — AI provider/model choices, API keys,
    and SMTP config, editable via the Setup page instead of .env. Seeded once
    from .env on first read (see store._seed_app_settings_row) so existing
    env-only deployments keep working unchanged until someone edits via the
    UI, after which the database is authoritative."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    llm_provider: Mapped[str] = mapped_column(String(32), default="openai")
    openai_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    anthropic_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    openai_chat_model: Mapped[str] = mapped_column(String(128), default="gpt-4o-mini")
    claude_model: Mapped[str] = mapped_column(String(128), default="claude-sonnet-4-6")
    embed_provider: Mapped[str] = mapped_column(String(32), default="openai")
    openai_embed_model: Mapped[str] = mapped_column(String(128), default="text-embedding-3-small")
    st_embed_model: Mapped[str] = mapped_column(String(128), default="all-MiniLM-L6-v2")
    embed_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hf_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_from: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TokenUsageEventRow(Base):
    """One row per LLM/embedding call, project-wide — chat, run-sql summaries,
    suggested questions, and every training embedding. No FK to connections:
    usage history must survive a connection being deleted, and some
    operations (e.g. training a manually-added SQL example) aren't
    connection-scoped at all."""

    __tablename__ = "token_usage_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(64))
    connection_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operation: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
