from typing import Literal, Optional
from pydantic import BaseModel, Field


class SchemaFieldDoc(BaseModel):
    fieldname: str
    label: str
    fieldtype: str
    description: Optional[str] = ""


# ---------- SQL Examples ----------

class SqlExampleBase(BaseModel):
    question: str
    sql: str
    module: Optional[str] = None
    # Required — no more "global" (connection_id=None) examples. Every
    # example, manual or imported, is scoped to the connection it was
    # written/imported for, so training data from one database is never
    # suggested as a reference pattern for an unrelated one (see rag.py's
    # build_context and train_sql_example_now).
    connection_id: str
    tags: list[str] = Field(default_factory=list)


class SqlExampleCreate(SqlExampleBase):
    pass


class SqlExampleUpdate(BaseModel):
    question: Optional[str] = None
    sql: Optional[str] = None
    module: Optional[str] = None
    # Optional here only because this is a partial-update payload — omitting
    # it means "leave the existing connection_id alone." An update can still
    # never set it to None/empty; see update_sql_example's validation.
    connection_id: Optional[str] = None
    tags: Optional[list[str]] = None


class SqlExample(SqlExampleBase):
    id: str
    created_at: str
    source: str = "manual"
    vote: Literal["up", "down"] = "up"
    # Set only for source="feedback" examples — the chat message this was
    # thumbs-up/down'd from, so deleting the example can clear that message's
    # feedback icon back to neutral instead of leaving it stuck "voted"
    # forever with nothing left backing it up.
    source_message_id: Optional[str] = None


SqlExampleImportStatus = Literal["idle", "running", "completed", "failed"]


class SqlExampleImportProgress(BaseModel):
    """Mirrors DescriptionImportProgress's shape (connections.py's bulk
    table/column-description import) — same "queue it, poll for progress"
    pattern, so a bulk import never blocks the request that started it (or
    the page it was started from) on however many rows/embeddings it has to
    process."""
    status: SqlExampleImportStatus = "idle"
    total_rows: int = 0
    processed_rows: int = 0
    imported_count: int = 0
    failed_count: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class SqlExampleBatchDeleteRequest(BaseModel):
    ids: list[str]


# ---------- Master Data ----------
# Real reference/lookup-table row data (e.g. a "Category" or "Status" table's
# actual rows), embedded so the LLM can resolve a name mentioned in a
# question (e.g. "Electronics") to the real value/id it maps to in that
# table, instead of guessing a literal. Import-only, like a table's real
# data would be — no manual single-row add/edit, since typing individual
# master-data rows by hand isn't a realistic workflow. See rag.py's
# train_master_data_row_now / build_context.

class MasterDataRecordBase(BaseModel):
    connection_id: str
    module: Optional[str] = None
    table_name: str
    # Arbitrary column -> value pairs, exactly as they appeared in the
    # uploaded file's header row — no fixed shape, since every table's
    # master data has different columns.
    row_data: dict[str, str] = Field(default_factory=dict)


class MasterDataRecord(MasterDataRecordBase):
    id: str
    created_at: str
    source: str = "excel_import"


MasterDataImportStatus = Literal["idle", "running", "completed", "failed"]


class MasterDataImportProgress(BaseModel):
    """Mirrors SqlExampleImportProgress's shape/pattern exactly — queued via
    BackgroundTasks, polled for progress. Keyed by (connection_id, table_name)
    rather than just connection_id, since a connection can have master data
    imports for several different tables in flight independently."""
    status: MasterDataImportStatus = "idle"
    table_name: Optional[str] = None
    total_rows: int = 0
    processed_rows: int = 0
    imported_count: int = 0
    failed_count: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class MasterDataBatchDeleteRequest(BaseModel):
    ids: list[str]


# ---------- Chat / Ask ----------

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


class AskRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    connection_id: Optional[str] = None
    module: Optional[str] = None


class RunSqlRequest(BaseModel):
    connection_id: str
    sql: str
    question: Optional[str] = None


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[dict]
    row_count: int
    execution_time_ms: int


class RunSqlResponse(QueryResult):
    summary: str
    follow_up_questions: list[str]


class AskResponse(BaseModel):
    message_id: str
    question: str
    sql: str
    explanation: str
    summary: str
    result: QueryResult
    token_usage: TokenUsage
    follow_up_questions: list[str]
    model_used: str
    generated_at: str
    connection_id: Optional[str] = None
    connection_name: Optional[str] = None


class FeedbackRequest(BaseModel):
    message_id: str
    question: str
    sql: str
    is_correct: bool = True


# ---------- Chat sessions & messages (server-side; was browser localStorage) ----------

FeedbackVote = Literal["up", "down"]


class ChatSessionBase(BaseModel):
    connection_id: Optional[str] = None


class ChatSessionCreate(ChatSessionBase):
    pass


class ChatSessionUpdate(BaseModel):
    title: Optional[str] = None
    connection_id: Optional[str] = None


class ChatSession(ChatSessionBase):
    id: str
    title: str = "New chat"
    created_at: str


class ChatMessageBase(BaseModel):
    role: Literal["user", "assistant"]
    question: Optional[str] = None
    ask: Optional[AskResponse] = None
    feedback: Optional[FeedbackVote] = None
    error: Optional[str] = None


class ChatMessageCreate(ChatMessageBase):
    id: Optional[str] = None  # client-generated, for optimistic UI before the round trip


class ChatMessageUpdate(BaseModel):
    ask: Optional[AskResponse] = None
    feedback: Optional[FeedbackVote] = None
    error: Optional[str] = None


class ChatMessage(ChatMessageBase):
    id: str
    created_at: str


# ---------- Reports ----------

class ReportBase(BaseModel):
    title: str
    description: Optional[str] = ""
    question: str
    sql: str
    columns: list[str]
    rows: list[dict]
    row_count: int
    connection_id: Optional[str] = None


class ReportCreate(ReportBase):
    pass


class ReportUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    sql: Optional[str] = None
    columns: Optional[list[str]] = None
    rows: Optional[list[dict]] = None
    row_count: Optional[int] = None


class Report(ReportBase):
    id: str
    created_at: str


class ReportRunRequest(BaseModel):
    sql: str


class ReportRunResult(BaseModel):
    columns: list[str]
    rows: list[dict]
    row_count: int
    execution_time_ms: int


# ---------- Scheduled Reports (cron-style email delivery) ----------

ScheduleFrequency = Literal["daily", "weekly", "monthly"]
ScheduleRunStatus = Literal["scheduled", "running", "success", "failed"]


class ReportScheduleBase(BaseModel):
    report_id: str
    frequency: ScheduleFrequency = "daily"
    time_of_day: str = "09:00"
    timezone: str = "UTC"  # IANA name (e.g. "Asia/Kolkata") — time_of_day is local to this
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    recipient_group: Optional[str] = ""
    recipient_emails: list[str] = Field(default_factory=list)
    is_active: bool = True


class ReportScheduleCreate(ReportScheduleBase):
    pass


class ReportScheduleUpdate(BaseModel):
    frequency: Optional[ScheduleFrequency] = None
    time_of_day: Optional[str] = None
    timezone: Optional[str] = None
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    recipient_group: Optional[str] = None
    recipient_emails: Optional[list[str]] = None
    is_active: Optional[bool] = None


class ReportSchedule(ReportScheduleBase):
    id: str
    cron_expression: str
    created_at: str
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None


class ScheduleRun(BaseModel):
    id: str
    schedule_id: str
    report_id: str
    status: ScheduleRunStatus
    started_at: str
    completed_at: Optional[str] = None
    row_count: Optional[int] = None
    recipients: list[str] = Field(default_factory=list)
    error: Optional[str] = None


# ---------- Database Connections & Schema Explorer ----------

DbType = Literal["mariadb", "frappe", "mysql", "postgres"]
ConnectionStatus = Literal["untested", "connected", "error"]
TrainingStatus = Literal["untrained", "queued", "training", "trained", "failed"]


class DatabaseConnectionBase(BaseModel):
    name: str
    db_type: DbType = "mariadb"
    host: str
    port: int = 3306
    database_name: str
    username: str
    password: Optional[str] = ""


class DatabaseConnectionCreate(DatabaseConnectionBase):
    pass


class DatabaseConnectionUpdate(BaseModel):
    name: Optional[str] = None
    db_type: Optional[DbType] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class DatabaseConnection(DatabaseConnectionBase):
    id: str
    status: ConnectionStatus = "untested"
    last_tested_at: Optional[str] = None
    created_at: str
    table_count: int = 0
    # How many of this connection's tables have training_status == "trained"
    # — used by the frontend to hide a connection from "which connection do
    # you want to use" pickers (chat/SQL examples/master data) until at
    # least one table has actually been trained, since asking a question or
    # importing training data against an untrained connection has nothing
    # to retrieve against yet. Computed in routers/connections.py's
    # _with_table_count, not stored — always derived from tables_store.
    trained_table_count: int = 0


class DatabaseConnectionOut(BaseModel):
    """Public/API-response shape of a DatabaseConnection. The raw password
    is deliberately never included here — only a `password_set` flag,
    matching the same "don't return secrets in plain text" convention
    AppSettings already uses for its API keys/SMTP password (see below).
    `DatabaseConnection` itself keeps the real password because internal
    code (app/db.py's get_raw_connection, app/store.py) needs it to
    actually open a connection — this model exists purely for what the API
    hands back to a browser."""

    id: str
    name: str
    db_type: DbType = "mariadb"
    host: str
    port: int = 3306
    database_name: str
    username: str
    password_set: bool = False
    status: ConnectionStatus = "untested"
    last_tested_at: Optional[str] = None
    created_at: str
    table_count: int = 0
    trained_table_count: int = 0

    @classmethod
    def from_connection(cls, conn: "DatabaseConnection") -> "DatabaseConnectionOut":
        return cls(**conn.model_dump(exclude={"password"}), password_set=bool(conn.password))


class ForeignKeyRef(BaseModel):
    column: str
    ref_table: str
    ref_column: str = "name"


class DbTableBase(BaseModel):
    description: Optional[str] = ""
    module: Optional[str] = None
    primary_key: Optional[str] = "name"
    is_child_table: bool = False
    parent_table: Optional[str] = None
    foreign_keys: list[ForeignKeyRef] = Field(default_factory=list)
    columns: list[SchemaFieldDoc] = Field(default_factory=list)


class DbTableUpdate(BaseModel):
    description: Optional[str] = None
    module: Optional[str] = None
    primary_key: Optional[str] = None
    is_child_table: Optional[bool] = None
    parent_table: Optional[str] = None
    foreign_keys: Optional[list[ForeignKeyRef]] = None
    columns: Optional[list[SchemaFieldDoc]] = None


class DbTable(DbTableBase):
    table_name: str
    doctype: str
    module: Optional[str] = None
    row_count: int
    training_status: TrainingStatus = "untrained"
    trained_at: Optional[str] = None
    vector_count: int = 0
    training_error: Optional[str] = None


class TrainSelectedRequest(BaseModel):
    table_names: list[str]


JobStatus = Literal["running", "completed"]


class TrainingJob(BaseModel):
    id: str
    connection_id: str
    table_names: list[str]
    total: int
    completed: int
    failed: int = 0
    status: JobStatus
    started_at: str
    completed_at: Optional[str] = None


DiscoveryStatus = Literal["idle", "running", "completed", "failed"]


class SchemaDiscoveryProgress(BaseModel):
    status: DiscoveryStatus = "idle"
    total: int = 0
    completed: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    table_count: int = 0
    error: Optional[str] = None


# ---------- Training stats ----------

class TrainingStats(BaseModel):
    connections_count: int
    trained_tables_count: int
    total_tables_count: int
    sql_example_count: int
    total_vectors: int


# ---------- App Settings (AI providers + SMTP, editable via the Setup page) ----------
# Secrets (API keys, SMTP password) are never returned in plain text — only a
# `<field>_set` boolean, matching the "leave blank to keep unchanged" pattern
# DatabaseConnectionUpdate already uses for passwords.

class AppSettings(BaseModel):
    llm_provider: str = "openai"
    openai_api_key_set: bool = False
    anthropic_api_key_set: bool = False
    openai_chat_model: str = "gpt-4o-mini"
    claude_model: str = "claude-sonnet-4-6"
    embed_provider: str = "openai"
    openai_embed_model: str = "text-embedding-3-small"
    st_embed_model: str = "all-MiniLM-L6-v2"
    embed_dim: Optional[int] = None
    hf_token_set: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password_set: bool = False
    smtp_from: str = ""


class AppSettingsUpdate(BaseModel):
    llm_provider: Optional[str] = None
    openai_api_key: Optional[str] = None  # omit/null = unchanged, "" = clear
    anthropic_api_key: Optional[str] = None
    openai_chat_model: Optional[str] = None
    claude_model: Optional[str] = None
    embed_provider: Optional[str] = None
    openai_embed_model: Optional[str] = None
    st_embed_model: Optional[str] = None
    embed_dim: Optional[int] = None
    hf_token: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None


# ---------- Token usage tracking ----------

TokenUsageOperation = Literal[
    "ask_sql_generation", "ask_summary", "ask_embedding", "run_sql_summary",
    "suggested_questions", "train_table", "train_column_doc", "train_sql_example",
]
TokenUsageCategory = Literal["llm", "embedding"]


class TokenUsageEvent(BaseModel):
    id: str
    created_at: str
    connection_id: Optional[str] = None
    operation: TokenUsageOperation
    category: TokenUsageCategory
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


# ---------- Usage Analytics models ----------

class UsageMetricSummary(BaseModel):
    total_requests: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    credits_used: float = 0.0
    credits_remaining: float = 10000.0
    total_budget_credits: float = 10000.0
    llm_requests: int = 0
    embedding_requests: int = 0
    cached_requests: int = 0


class UsageBreakdownItem(BaseModel):
    name: str
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    credits_used: float = 0.0


class UsageTrendItem(BaseModel):
    date: str
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    credits_used: float = 0.0


class RecentUsageItem(BaseModel):
    id: str
    created_at: str
    connection_name: str
    operation: str
    category: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    credits_used: float


class UsageOverviewResponse(BaseModel):
    overall: UsageMetricSummary
    today: UsageMetricSummary
    this_week: UsageMetricSummary
    this_month: UsageMetricSummary
    by_model: list[UsageBreakdownItem]
    by_operation: list[UsageBreakdownItem]
    by_connection: list[UsageBreakdownItem]
    recent_events: list[RecentUsageItem]


class DescriptionImportResponse(BaseModel):
    updated_tables_count: int
    updated_columns_count: int
    retrained_tables_count: int
    failed_count: int
    errors: list[str]


ImportStatus = Literal["idle", "running", "completed", "failed"]


class DescriptionImportProgress(BaseModel):
    status: ImportStatus = "idle"
    total_rows: int = 0
    processed_rows: int = 0
    updated_tables_count: int = 0
    updated_columns_count: int = 0
    retrained_tables_count: int = 0
    failed_count: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None



