"""Metadata stores for app-level objects (connections, reports, schedules,
SQL examples, training jobs) — persisted in the metadata MariaDB database
(app/database.py) so they survive a backend restart.

These are NOT the user's data — they're QuickInsights' own bookkeeping about
what connections/reports/schedules exist. The user's actual data lives in
their real MariaDB database (accessed via app/db.py) and the RAG training
data lives in real Qdrant collections (via app/vector_store.py).

Each module-level `*_store` object below is a dict-like façade over a
SQLAlchemy table: routers can keep using `store.x[id]`, `.get()`, `.values()`,
`del store.x[id]`, etc. exactly like the old in-memory dicts, but every read
and write is a round trip to the database, so nothing here needs its own
in-process cache or explicit hydration step.
"""
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import config as _config
from app import crypto
from app.database import SessionLocal
from app.db_models import (
    AppSettingsRow,
    ChatMessageRow,
    ChatSessionRow,
    ConnectionRow,
    DbTableRow,
    DiscoveryProgressRow,
    MasterDataRecordRow,
    ReportRow,
    ReportScheduleRow,
    ScheduleRunRow,
    SqlExampleRow,
    TokenUsageEventRow,
    TrainingJobRow,
)
from app.models import (
    AppSettings,
    AppSettingsUpdate,
    AskResponse,
    ChatMessage,
    ChatMessageUpdate,
    ChatSession,
    DatabaseConnection,
    DbTable,
    DescriptionImportProgress,
    ForeignKeyRef,
    MasterDataImportProgress,
    MasterDataRecord,
    Report,
    ReportSchedule,
    SchemaDiscoveryProgress,
    SchemaFieldDoc,
    ScheduleRun,
    SqlExample,
    SqlExampleImportProgress,
    TokenUsageEvent,
    TrainingJob,
)
from app.pricing import estimate_cost_usd

logger = logging.getLogger(__name__)


def now_fn() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id_fn() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def _session():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception as e:
        print(f"Error in metadata DB session -- {e}")
        logger.exception("Error in metadata DB session")
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Generic dict-like façade over a flat SQLAlchemy table (single-column PK).
# ---------------------------------------------------------------------------

class SqlBackedDict:
    def __init__(self, model_cls, pk_column: str, to_pydantic, to_row_kwargs):
        self._model = model_cls
        self._pk = pk_column
        self._to_pydantic = to_pydantic
        self._to_row_kwargs = to_row_kwargs

    def get(self, key, default=None):
        with _session() as s:
            row = s.get(self._model, key)
            return self._to_pydantic(row) if row else default

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        kwargs = self._to_row_kwargs(value)
        with _session() as s:
            row = s.get(self._model, key)
            if row:
                for k, v in kwargs.items():
                    setattr(row, k, v)
            else:
                s.add(self._model(**kwargs))

    def __delitem__(self, key):
        with _session() as s:
            row = s.get(self._model, key)
            if not row:
                raise KeyError(key)
            s.delete(row)

    def __contains__(self, key):
        with _session() as s:
            return s.get(self._model, key) is not None

    def __iter__(self):
        with _session() as s:
            return iter([getattr(r, self._pk) for r in s.query(self._model).all()])

    def __len__(self):
        with _session() as s:
            return s.query(self._model).count()

    def values(self):
        with _session() as s:
            return [self._to_pydantic(r) for r in s.query(self._model).all()]

    def items(self):
        with _session() as s:
            return [(getattr(r, self._pk), self._to_pydantic(r)) for r in s.query(self._model).all()]

    def keys(self):
        with _session() as s:
            return [getattr(r, self._pk) for r in s.query(self._model).all()]

    def clear(self):
        with _session() as s:
            s.query(self._model).delete()

    def pop(self, key, default=None):
        value = self.get(key, default)
        with _session() as s:
            row = s.get(self._model, key)
            if row:
                s.delete(row)
        return value

    def delete_where(self, predicate) -> None:
        """Delete every row whose Pydantic value matches predicate(value) —
        the DB-backed replacement for the old `store.x = {k: v for ... if ...}`
        whole-dict-reassignment pattern (which would have silently swapped
        this façade out for a plain dict and lost persistence)."""
        with _session() as s:
            for row in s.query(self._model).all():
                if predicate(self._to_pydantic(row)):
                    s.delete(row)


# ---------------------------------------------------------------------------
# Conversion helpers: ORM row <-> Pydantic model
# ---------------------------------------------------------------------------

def _connection_to_pydantic(row: ConnectionRow) -> DatabaseConnection:
    return DatabaseConnection(
        id=row.id,
        name=row.name,
        db_type=row.db_type,
        host=row.host,
        port=row.port,
        database_name=row.database_name,
        username=row.username,
        password=crypto.decrypt(row.password_encrypted),
        status=row.status,
        last_tested_at=row.last_tested_at,
        created_at=row.created_at,
    )


def _connection_to_row_kwargs(conn: DatabaseConnection) -> dict:
    return dict(
        id=conn.id,
        name=conn.name,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database_name=conn.database_name,
        username=conn.username,
        password_encrypted=crypto.encrypt(conn.password),
        status=conn.status,
        last_tested_at=conn.last_tested_at,
        created_at=conn.created_at,
    )


def _chat_session_to_pydantic(row: ChatSessionRow) -> ChatSession:
    return ChatSession(id=row.id, title=row.title, connection_id=row.connection_id, created_at=row.created_at)


def _chat_session_to_row_kwargs(s: ChatSession) -> dict:
    return dict(id=s.id, title=s.title, connection_id=s.connection_id, created_at=s.created_at)


def _chat_message_to_pydantic(row: ChatMessageRow) -> ChatMessage:
    return ChatMessage(
        id=row.id, role=row.role, question=row.question, created_at=row.created_at,
        ask=AskResponse(**row.ask) if row.ask else None,
        feedback=row.feedback, error=row.error,
    )


def _sql_example_to_pydantic(row: SqlExampleRow) -> SqlExample:
    return SqlExample(
        id=row.id, question=row.question, sql=row.sql, module=row.module,
        connection_id=row.connection_id, tags=row.tags or [],
        created_at=row.created_at, source=row.source, vote=row.vote or "up",
        source_message_id=row.source_message_id,
    )


def _sql_example_to_row_kwargs(ex: SqlExample) -> dict:
    return dict(
        id=ex.id, question=ex.question, sql=ex.sql, module=ex.module,
        connection_id=ex.connection_id, tags=ex.tags,
        created_at=ex.created_at, source=ex.source, vote=ex.vote,
        source_message_id=ex.source_message_id,
    )


def _master_data_record_to_pydantic(row: MasterDataRecordRow) -> MasterDataRecord:
    return MasterDataRecord(
        id=row.id, connection_id=row.connection_id, module=row.module,
        table_name=row.table_name, row_data=row.row_data or {},
        created_at=row.created_at, source=row.source,
    )


def _master_data_record_to_row_kwargs(rec: MasterDataRecord) -> dict:
    return dict(
        id=rec.id, connection_id=rec.connection_id, module=rec.module,
        table_name=rec.table_name, row_data=rec.row_data,
        created_at=rec.created_at, source=rec.source,
    )


def find_exact_sql_example(question: str) -> SqlExample | None:
    """Look up a confirmed (thumbs-up) example whose question matches this one
    verbatim (case/whitespace-insensitive), so an exact repeat question can
    reuse the known-good SQL instead of asking the LLM to regenerate it."""
    normalized = " ".join(question.strip().lower().split())
    if not normalized:
        return None
    matches = [
        ex for ex in sql_example_store.values()
        if ex.vote == "up" and " ".join(ex.question.strip().lower().split()) == normalized
    ]
    if not matches:
        return None
    return max(matches, key=lambda ex: ex.created_at)


def _report_to_pydantic(row: ReportRow) -> Report:
    return Report(
        id=row.id, title=row.title, description=row.description or "", question=row.question,
        sql=row.sql, columns=row.columns or [], rows=row.rows or [], row_count=row.row_count,
        connection_id=row.connection_id, created_at=row.created_at,
    )


def _report_to_row_kwargs(r: Report) -> dict:
    return dict(
        id=r.id, title=r.title, description=r.description, question=r.question, sql=r.sql,
        columns=r.columns, rows=r.rows, row_count=r.row_count, connection_id=r.connection_id,
        created_at=r.created_at,
    )


def _schedule_to_pydantic(row: ReportScheduleRow) -> ReportSchedule:
    return ReportSchedule(
        id=row.id, report_id=row.report_id, frequency=row.frequency, time_of_day=row.time_of_day,
        timezone=row.timezone or "UTC", day_of_week=row.day_of_week, day_of_month=row.day_of_month,
        recipient_group=row.recipient_group or "", recipient_emails=row.recipient_emails or [],
        is_active=row.is_active, cron_expression=row.cron_expression, created_at=row.created_at,
        last_run_at=row.last_run_at, next_run_at=row.next_run_at,
    )


def _schedule_to_row_kwargs(sc: ReportSchedule) -> dict:
    return dict(
        id=sc.id, report_id=sc.report_id, frequency=sc.frequency, time_of_day=sc.time_of_day,
        timezone=sc.timezone, day_of_week=sc.day_of_week, day_of_month=sc.day_of_month,
        recipient_group=sc.recipient_group, recipient_emails=sc.recipient_emails, is_active=sc.is_active,
        cron_expression=sc.cron_expression, created_at=sc.created_at, last_run_at=sc.last_run_at,
        next_run_at=sc.next_run_at,
    )


def _schedule_run_to_pydantic(row: ScheduleRunRow) -> ScheduleRun:
    return ScheduleRun(
        id=row.id, schedule_id=row.schedule_id, report_id=row.report_id, status=row.status,
        started_at=row.started_at, completed_at=row.completed_at, row_count=row.row_count,
        recipients=row.recipients or [], error=row.error,
    )


def _schedule_run_to_row_kwargs(run: ScheduleRun) -> dict:
    return dict(
        id=run.id, schedule_id=run.schedule_id, report_id=run.report_id, status=run.status,
        started_at=run.started_at, completed_at=run.completed_at, row_count=run.row_count,
        recipients=run.recipients, error=run.error,
    )


def _training_job_to_pydantic(row: TrainingJobRow) -> TrainingJob:
    return TrainingJob(
        id=row.id, connection_id=row.connection_id, table_names=row.table_names or [],
        total=row.total, completed=row.completed, failed=row.failed or 0, status=row.status,
        started_at=row.started_at, completed_at=row.completed_at,
    )


def _training_job_to_row_kwargs(job: TrainingJob) -> dict:
    return dict(
        id=job.id, connection_id=job.connection_id, table_names=job.table_names, total=job.total,
        completed=job.completed, failed=job.failed, status=job.status, started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _token_usage_event_to_pydantic(row: TokenUsageEventRow) -> TokenUsageEvent:
    return TokenUsageEvent(
        id=row.id, created_at=row.created_at, connection_id=row.connection_id,
        operation=row.operation, category=row.category, provider=row.provider, model=row.model,
        prompt_tokens=row.prompt_tokens, completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens, estimated_cost_usd=row.estimated_cost_usd,
    )


def _token_usage_event_to_row_kwargs(event: TokenUsageEvent) -> dict:
    return dict(
        id=event.id, created_at=event.created_at, connection_id=event.connection_id,
        operation=event.operation, category=event.category, provider=event.provider, model=event.model,
        prompt_tokens=event.prompt_tokens, completion_tokens=event.completion_tokens,
        total_tokens=event.total_tokens, estimated_cost_usd=event.estimated_cost_usd,
    )


def _discovery_progress_to_pydantic(row: DiscoveryProgressRow) -> SchemaDiscoveryProgress:
    return SchemaDiscoveryProgress(
        status=row.status, total=row.total, completed=row.completed, started_at=row.started_at,
        completed_at=row.completed_at, table_count=row.table_count, error=row.error,
    )


def _discovery_progress_to_row_kwargs(conn_id: str, p: SchemaDiscoveryProgress) -> dict:
    return dict(
        connection_id=conn_id, status=p.status, total=p.total, completed=p.completed,
        started_at=p.started_at, completed_at=p.completed_at, table_count=p.table_count, error=p.error,
    )


def _table_to_pydantic(row: DbTableRow) -> DbTable:
    return DbTable(
        table_name=row.table_name, doctype=row.doctype, module=row.module, row_count=row.row_count,
        description=row.description or "", primary_key=row.primary_key,
        is_child_table=row.is_child_table, parent_table=row.parent_table,
        foreign_keys=[ForeignKeyRef(**fk) for fk in (row.foreign_keys or [])],
        columns=[SchemaFieldDoc(**c) for c in (row.columns or [])],
        training_status=row.training_status, trained_at=row.trained_at,
        vector_count=row.vector_count, training_error=row.training_error,
    )


def _table_to_row_kwargs(conn_id: str, t: DbTable) -> dict:
    return dict(
        connection_id=conn_id, table_name=t.table_name, doctype=t.doctype, module=t.module, row_count=t.row_count,
        description=t.description, primary_key=t.primary_key, is_child_table=t.is_child_table,
        parent_table=t.parent_table, foreign_keys=[fk.model_dump() for fk in t.foreign_keys],
        columns=[c.model_dump() for c in t.columns], training_status=t.training_status,
        trained_at=t.trained_at, vector_count=t.vector_count, training_error=t.training_error,
    )


# ---------------------------------------------------------------------------
# tables_store: dict[connection_id -> dict[table_name -> DbTable]]
# ---------------------------------------------------------------------------

class ConnectionTables:
    """dict-like view over this one connection's `db_tables` rows."""

    def __init__(self, conn_id: str):
        self.conn_id = conn_id

    def get(self, table_name, default=None):
        with _session() as s:
            row = s.get(DbTableRow, (self.conn_id, table_name))
            return _table_to_pydantic(row) if row else default

    def __getitem__(self, table_name):
        value = self.get(table_name)
        if value is None:
            raise KeyError(table_name)
        return value

    def __setitem__(self, table_name, table: DbTable):
        kwargs = _table_to_row_kwargs(self.conn_id, table)
        with _session() as s:
            row = s.get(DbTableRow, (self.conn_id, table_name))
            if row:
                for k, v in kwargs.items():
                    setattr(row, k, v)
            else:
                s.add(DbTableRow(**kwargs))

    def __contains__(self, table_name):
        with _session() as s:
            return s.get(DbTableRow, (self.conn_id, table_name)) is not None

    def __len__(self):
        with _session() as s:
            return s.query(DbTableRow).filter(DbTableRow.connection_id == self.conn_id).count()

    def __iter__(self):
        return iter(self.keys())

    def keys(self):
        with _session() as s:
            rows = s.query(DbTableRow).filter(DbTableRow.connection_id == self.conn_id).all()
            return [r.table_name for r in rows]

    def values(self):
        with _session() as s:
            rows = s.query(DbTableRow).filter(DbTableRow.connection_id == self.conn_id).all()
            return [_table_to_pydantic(r) for r in rows]

    def items(self):
        with _session() as s:
            rows = s.query(DbTableRow).filter(DbTableRow.connection_id == self.conn_id).all()
            return [(r.table_name, _table_to_pydantic(r)) for r in rows]


class TablesStore:
    """dict-like façade for `store.tables_store` — keyed by connection_id,
    each value a ConnectionTables view over that connection's tables."""

    def get(self, conn_id, default=None):
        return ConnectionTables(conn_id)

    def __getitem__(self, conn_id):
        return ConnectionTables(conn_id)

    def __setitem__(self, conn_id, tables: dict):
        """Wholesale-replace a connection's table set (used after schema
        (re)discovery) — delete existing rows for it, then insert the new
        ones, in one transaction."""
        with _session() as s:
            s.query(DbTableRow).filter(DbTableRow.connection_id == conn_id).delete()
            for name, table in tables.items():
                s.add(DbTableRow(**_table_to_row_kwargs(conn_id, table)))

    def pop(self, conn_id, default=None):
        with _session() as s:
            s.query(DbTableRow).filter(DbTableRow.connection_id == conn_id).delete()
        return default

    def __contains__(self, conn_id):
        with _session() as s:
            return s.query(DbTableRow).filter(DbTableRow.connection_id == conn_id).count() > 0

    def items(self):
        with _session() as s:
            conn_ids = [r.id for r in s.query(ConnectionRow).all()]
        return [(cid, ConnectionTables(cid)) for cid in conn_ids]

    def values(self):
        return [tables for _cid, tables in self.items()]

    def keys(self):
        return [cid for cid, _tables in self.items()]

    def __iter__(self):
        return iter(self.keys())


# ---------------------------------------------------------------------------
# Public stores — same names/shapes routers already import from this module.
# ---------------------------------------------------------------------------

chat_session_store = SqlBackedDict(ChatSessionRow, "id", _chat_session_to_pydantic, _chat_session_to_row_kwargs)
sql_example_store = SqlBackedDict(SqlExampleRow, "id", _sql_example_to_pydantic, _sql_example_to_row_kwargs)
master_data_record_store = SqlBackedDict(
    MasterDataRecordRow, "id", _master_data_record_to_pydantic, _master_data_record_to_row_kwargs
)
report_store = SqlBackedDict(ReportRow, "id", _report_to_pydantic, _report_to_row_kwargs)
schedule_store = SqlBackedDict(ReportScheduleRow, "id", _schedule_to_pydantic, _schedule_to_row_kwargs)
schedule_run_store = SqlBackedDict(ScheduleRunRow, "id", _schedule_run_to_pydantic, _schedule_run_to_row_kwargs)
connections_store = SqlBackedDict(ConnectionRow, "id", _connection_to_pydantic, _connection_to_row_kwargs)
training_job_store = SqlBackedDict(TrainingJobRow, "id", _training_job_to_pydantic, _training_job_to_row_kwargs)
token_usage_event_store = SqlBackedDict(
    TokenUsageEventRow, "id", _token_usage_event_to_pydantic, _token_usage_event_to_row_kwargs
)
tables_store = TablesStore()
import_progress_store: dict[str, DescriptionImportProgress] = {}
# Keyed by connection_id — plain in-memory dict, same tradeoff as
# import_progress_store above (mutated in place by the background job, so
# any concurrent GET .../import/progress poll sees updates immediately with
# no DB round trip; doesn't survive a backend restart, single-process only).
sql_example_import_progress_store: dict[str, SqlExampleImportProgress] = {}
# Keyed by "{connection_id}:{table_name}" — unlike SQL examples (one import
# in flight per connection at a time), a connection can have master-data
# imports for several different tables running independently, so the key
# needs to include which table this progress record is for.
master_data_import_progress_store: dict[str, MasterDataImportProgress] = {}


def record_token_usage(
    *,
    operation: str,
    category: str,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    connection_id: str | None = None,
) -> TokenUsageEvent:
    """Project-wide token usage tracking — one row per LLM/embedding call.
    Callers should wrap this in try/except (a tracking hiccup must never
    break the actual RAG/training flow it's recording)."""
    total_tokens = prompt_tokens + completion_tokens
    event = TokenUsageEvent(
        id=new_id_fn(),
        created_at=now_fn(),
        connection_id=connection_id,
        operation=operation,
        category=category,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimate_cost_usd(model, prompt_tokens, completion_tokens),
    )
    token_usage_event_store[event.id] = event
    return event


class DiscoveryProgressStore(SqlBackedDict):
    def __setitem__(self, conn_id, progress: SchemaDiscoveryProgress):
        kwargs = _discovery_progress_to_row_kwargs(conn_id, progress)
        with _session() as s:
            row = s.get(DiscoveryProgressRow, conn_id)
            if row:
                for k, v in kwargs.items():
                    setattr(row, k, v)
            else:
                s.add(DiscoveryProgressRow(**kwargs))


# Keyed by connection_id -> SchemaDiscoveryProgress, one in-flight/last-run
# discovery per connection (see rag.py / routers/connections.py).
discovery_progress_store = DiscoveryProgressStore(
    DiscoveryProgressRow, "connection_id", _discovery_progress_to_pydantic, None
)


# ---------------------------------------------------------------------------
# App settings — singleton row (AI provider/model choices, API keys, SMTP),
# editable via the Setup page instead of .env. Seeded once from .env on first
# read so existing env-only deployments keep working unchanged; the database
# is authoritative from then on.
# ---------------------------------------------------------------------------

_APP_SETTINGS_SECRET_FIELDS = {
    "openai_api_key": "openai_api_key_encrypted",
    "anthropic_api_key": "anthropic_api_key_encrypted",
    "hf_token": "hf_token_encrypted",
    "smtp_password": "smtp_password_encrypted",
}


def _seed_app_settings_row() -> AppSettingsRow:
    return AppSettingsRow(
        id=1,
        llm_provider=_config.LLM_PROVIDER,
        openai_api_key_encrypted=crypto.encrypt(_config.OPENAI_API_KEY or None),
        anthropic_api_key_encrypted=crypto.encrypt(_config.ANTHROPIC_API_KEY or None),
        openai_chat_model=_config.OPENAI_CHAT_MODEL,
        claude_model=_config.CLAUDE_MODEL,
        embed_provider=_config.EMBED_PROVIDER,
        openai_embed_model=_config.OPENAI_EMBED_MODEL,
        st_embed_model=_config.ST_EMBED_MODEL,
        embed_dim=_config.EMBED_DIM,
        hf_token_encrypted=crypto.encrypt(os.environ.get("HF_TOKEN") or None),
        smtp_host=_config.SMTP_HOST,
        smtp_port=_config.SMTP_PORT,
        smtp_user=_config.SMTP_USER,
        smtp_password_encrypted=crypto.encrypt(_config.SMTP_PASSWORD or None),
        smtp_from=_config.SMTP_FROM,
    )


def _get_or_seed_app_settings_row(s) -> AppSettingsRow:
    row = s.get(AppSettingsRow, 1)
    if not row:
        row = _seed_app_settings_row()
        s.add(row)
        s.flush()
    return row


def get_app_settings() -> AppSettings:
    """Public, API-facing view — secrets are booleans (`<field>_set`), never
    the plaintext value. Used by GET /api/settings."""
    with _session() as s:
        row = _get_or_seed_app_settings_row(s)
        return AppSettings(
            llm_provider=row.llm_provider,
            openai_api_key_set=bool(row.openai_api_key_encrypted),
            anthropic_api_key_set=bool(row.anthropic_api_key_encrypted),
            openai_chat_model=row.openai_chat_model,
            claude_model=row.claude_model,
            embed_provider=row.embed_provider,
            openai_embed_model=row.openai_embed_model,
            st_embed_model=row.st_embed_model,
            embed_dim=row.embed_dim,
            hf_token_set=bool(row.hf_token_encrypted),
            smtp_host=row.smtp_host or "",
            smtp_port=row.smtp_port,
            smtp_user=row.smtp_user or "",
            smtp_password_set=bool(row.smtp_password_encrypted),
            smtp_from=row.smtp_from or "",
        )


def get_app_settings_raw() -> dict:
    """Internal-only accessor with DECRYPTED secrets — used by llm.py,
    embeddings.py, email_util.py, vector_store.py. Never exposed via the API;
    use get_app_settings() for that."""
    with _session() as s:
        row = _get_or_seed_app_settings_row(s)
        return dict(
            llm_provider=row.llm_provider,
            openai_api_key=crypto.decrypt(row.openai_api_key_encrypted) or "",
            anthropic_api_key=crypto.decrypt(row.anthropic_api_key_encrypted) or "",
            openai_chat_model=row.openai_chat_model,
            claude_model=row.claude_model,
            embed_provider=row.embed_provider,
            openai_embed_model=row.openai_embed_model,
            st_embed_model=row.st_embed_model,
            embed_dim=row.embed_dim,
            hf_token=crypto.decrypt(row.hf_token_encrypted) or "",
            smtp_host=row.smtp_host or "",
            smtp_port=row.smtp_port,
            smtp_user=row.smtp_user or "",
            smtp_password=crypto.decrypt(row.smtp_password_encrypted) or "",
            smtp_from=row.smtp_from or "",
        )


def update_app_settings(patch: AppSettingsUpdate) -> AppSettings:
    """Same "omit/null = unchanged" convention every other *Update schema in
    this app uses. For secret fields, an explicit "" clears the saved value
    (distinct from omitting the field, which leaves it untouched)."""
    changes = {k: v for k, v in patch.model_dump().items() if v is not None}
    with _session() as s:
        row = _get_or_seed_app_settings_row(s)
        for key, value in changes.items():
            if key in _APP_SETTINGS_SECRET_FIELDS:
                setattr(row, _APP_SETTINGS_SECRET_FIELDS[key], crypto.encrypt(value) if value else None)
            else:
                setattr(row, key, value)
    return get_app_settings()


# ---------------------------------------------------------------------------
# Chat messages — ordered per session by `seq` (an auto-increment surrogate
# key), not by `id` (the client-generated id used for optimistic UI). Not a
# SqlBackedDict since callers need ordered list-per-session access, not
# single-key lookup.
# ---------------------------------------------------------------------------

def get_chat_message(message_id: str) -> ChatMessage | None:
    """Looked up by id alone, unlike list/update below — client-generated ids
    are unique across every session, so no session_id is needed here."""
    with _session() as s:
        row = s.query(ChatMessageRow).filter(ChatMessageRow.id == message_id).one_or_none()
        return _chat_message_to_pydantic(row) if row else None


def clear_chat_message_feedback(message_id: str) -> None:
    """Resets a chat message's feedback icon back to neutral — used when the
    SqlExample it produced gets deleted from the SQL Examples page, so the
    chat UI doesn't keep showing a message as "voted" when nothing backing
    that vote exists anymore. Looked up by id alone, same as get_chat_message
    above, since the caller (sql_examples.py) only has the example's stored
    source_message_id, not which session it belongs to."""
    with _session() as s:
        row = s.query(ChatMessageRow).filter(ChatMessageRow.id == message_id).one_or_none()
        if row:
            row.feedback = None


def list_chat_messages(session_id: str) -> list[ChatMessage]:
    with _session() as s:
        rows = (
            s.query(ChatMessageRow)
            .filter(ChatMessageRow.session_id == session_id)
            .order_by(ChatMessageRow.seq)
            .all()
        )
        return [_chat_message_to_pydantic(r) for r in rows]


def add_chat_message(session_id: str, message: ChatMessage) -> ChatMessage:
    with _session() as s:
        s.add(
            ChatMessageRow(
                id=message.id,
                session_id=session_id,
                role=message.role,
                question=message.question,
                created_at=message.created_at,
                ask=message.ask.model_dump() if message.ask else None,
                feedback=message.feedback,
                error=message.error,
            )
        )
    return message


def update_chat_message(session_id: str, message_id: str, patch: ChatMessageUpdate) -> ChatMessage:
    # exclude_unset (not "if v is not None") so an explicitly-sent
    # `{"feedback": null}` actually clears the field — "if v is not None"
    # made that indistinguishable from the field being omitted entirely, so
    # feedback could only ever be changed to "up"/"down", never reset back
    # to neutral through this endpoint. (routers/chat.py's DELETE
    # /api/feedback/{message_id} doesn't go through this function — it
    # calls clear_chat_message_feedback directly — but this is still a real
    # correctness fix for this endpoint on its own.)
    changes = patch.model_dump(exclude_unset=True)
    with _session() as s:
        row = (
            s.query(ChatMessageRow)
            .filter(ChatMessageRow.session_id == session_id, ChatMessageRow.id == message_id)
            .one_or_none()
        )
        if not row:
            raise KeyError(message_id)
        if "ask" in changes:
            row.ask = changes["ask"]
        if "feedback" in changes:
            row.feedback = changes["feedback"]
        if "error" in changes:
            row.error = changes["error"]
        return _chat_message_to_pydantic(row)


def compute_cron_expression(
    frequency: str, time_of_day: str, day_of_week: int | None, day_of_month: int | None
) -> str:
    """Display-only (shown as reference, e.g. in an "advanced" view) — actual
    firing is driven by next_run_at, computed timezone-aware in compute_next_run."""
    hh, mm = time_of_day.split(":")
    if frequency == "weekly":
        dow = day_of_week if day_of_week is not None else 1
        return f"{int(mm)} {int(hh)} * * {dow}"
    if frequency == "monthly":
        dom = day_of_month if day_of_month is not None else 1
        return f"{int(mm)} {int(hh)} {dom} * *"
    return f"{int(mm)} {int(hh)} * * *"


def compute_next_run(
    frequency: str,
    time_of_day: str,
    day_of_week: int | None,
    day_of_month: int | None,
    after: datetime,
    tz_name: str = "UTC",
) -> str:
    """`time_of_day` ("HH:MM") is local to `tz_name` (an IANA name, e.g.
    "Asia/Kolkata") — NOT UTC. All the day/week/month arithmetic below happens
    in that local timezone (so e.g. "12:15" really means 12:15 there, DST
    included), and only the final result is converted back to UTC, since
    that's what's stored/compared against elsewhere (the scheduler poller
    compares next_run_at to datetime.now(timezone.utc))."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    after_local = after.astimezone(tz)
    hh, mm = map(int, time_of_day.split(":"))
    candidate = after_local.replace(hour=hh, minute=mm, second=0, microsecond=0)

    if frequency == "weekly":
        target_dow = day_of_week if day_of_week is not None else 1
        while candidate.weekday() != target_dow or candidate <= after_local:
            candidate += timedelta(days=1)
    elif frequency == "monthly":
        target_dom = min(day_of_month if day_of_month is not None else 1, 28)
        candidate = candidate.replace(day=target_dom)
        if candidate <= after_local:
            month = candidate.month % 12 + 1
            year = candidate.year + (1 if candidate.month == 12 else 0)
            candidate = candidate.replace(year=year, month=month, day=target_dom)
    else:  # daily
        if candidate <= after_local:
            candidate += timedelta(days=1)

    return candidate.astimezone(timezone.utc).isoformat()
