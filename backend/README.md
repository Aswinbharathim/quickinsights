# QuickInsights API (real backend)

FastAPI backend for the Chat-with-your-Database RAG UI, backed by real infrastructure:

- **Real MariaDB/MySQL/Postgres** — connects to whichever database each saved Connection points at (via `pymysql`)
- **Real Qdrant vector store** — one collection per connection for trained schema, plus a shared collection for SQL examples
- **Real metadata database (MariaDB)** — connections, reports, schedules, SQL examples, and training state are persisted here, so they (and the "is this table trained?" status referencing your Qdrant vectors) survive a backend restart
- **Real LLM** — OpenAI (default) or Anthropic Claude for SQL generation, explanations, summaries, and follow-up questions
- **Real safety guardrail** — every generated (or user-edited) query is checked SELECT-only before it touches your database

There is no seeded demo data — connections, reports, schedules, and SQL examples all start empty and are created through the UI.

## Setup

### 1. Python environment

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

If you want local, free embeddings instead of OpenAI's, also run:
```bash
pip install sentence-transformers torch
# CPU-only machines: pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### 2. Metadata database + Qdrant

```bash
./setup_metadata_db.sh
```

Interactive — asks which of two modes to use (press **Enter** to accept the
default, standalone Docker — no need to know or care about the question if
that's all you want), then handles Qdrant, `.env`, and `ENCRYPTION_KEY` for
you either way:

- **Docker (default)** — standalone setups with no MariaDB server already
  available. Runs a bundled MariaDB 10.6 container (same version Frappe
  v14/v15 recommend, upgrades cleanly to 10.11/11.x later).
- **Frappe** — integrating alongside an existing Frappe bench (or any other
  MariaDB server you already run). Creates a new database + user *on that
  existing server* instead of running a second MariaDB — prompts for its
  host/port and root credentials, then writes the new connection as
  `METADATA_DATABASE_URL` in `.env`.

Either way this is a database **separate from** whatever you connect to
through the Connections page — it's QuickInsights' own bookkeeping (
connections/reports/schedules/SQL examples/training state), not your data.

Prefer to do it by hand instead of the script? `docker compose up -d qdrant`
starts just Qdrant; add `docker compose --profile docker-db up -d mariadb` for
the bundled container, or set `METADATA_DATABASE_URL` in `.env` yourself to
point at an existing server.

### 3. Configure

```bash
cp .env.example .env   # skip if setup_metadata_db.sh already created it
```

Fill in `OPENAI_API_KEY` (required — used for embeddings even if `LLM_PROVIDER=anthropic`, since Anthropic has no embeddings API), and optionally `ANTHROPIC_API_KEY` if you set `LLM_PROVIDER=anthropic`.

Note: **target** database credentials (the databases you *chat with*) are not
set here — add each one as a Connection through the app's Connections page
(host/port/user/password/db name are stored per connection, encrypted at rest,
so this backend can talk to several different databases at once). The
`METADATA_DB_*` / `METADATA_DATABASE_URL` / `ENCRYPTION_KEY` variables are for
QuickInsights' own storage only (step 2 above already set these for you).

### 4. Run

```bash
uvicorn app.main:app --reload --port 8000
```

The metadata database's schema is migrated automatically on startup (Alembic,
see `migrations/`) — no separate migration command needed in dev. To manage
migrations manually (e.g. after changing `app/db_models.py`):
```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

API docs: http://localhost:8000/docs

### Logs

Everything the app prints (every request, every `Error ... -- {e}` line) is
also written to `logs/app.log`, rotating daily at midnight with 7 days kept
(older files auto-deleted) — see `app/logging_config.py`. Your terminal output
is unchanged; the log file is an additional, persistent copy of the same
output. `logs/` is gitignored.

## Using it

1. **Connections** page → add a connection → **Test** (verifies real connectivity) → **Discover Schema** (real `SHOW TABLES`/`SHOW COLUMNS`/`tabDocField` introspection) → **Train** one or more tables (embeds each table's schema + relationships into that connection's Qdrant collection)
2. **Chat** page → pick the connection → ask a question in plain English — this retrieves the relevant trained schema + any saved SQL examples, asks the LLM to write a SELECT query + explanation, runs the SELECT-only guardrail, executes it against your real database, and asks the LLM to summarize the results and suggest follow-ups
3. Thumbs-up a good answer (or use **SQL Examples**) to save it as a few-shot example — it's embedded into a shared example bank used for every future question, on every connection
4. **Reports** → save a good chat answer, re-run edited SQL live against its connection
5. **Scheduled Reports** → cron-style recurring runs against the report's connection; **Run now** executes it immediately (email delivery is best-effort via SMTP if configured, see `.env.example`)
6. **Training Overview** (`Settings`) → real aggregate stats pulled from Qdrant's `count()` API; **Delete ALL training data** drops and recreates every Qdrant collection
7. **Setup** → LLM/embedding provider, API keys (OpenAI/Anthropic/Hugging Face), and SMTP — edited here and persisted in the metadata database, not `.env`. The `.env` values for these are only a one-time seed on first startup (see `.env.example`); after that, this page is the source of truth and takes effect immediately, no restart needed.

## Endpoints

- `GET/PUT /api/settings` — LLM/embedding provider, API keys, SMTP (Setup page). Secrets are write-only: GET returns `<field>_set` booleans, never plaintext.
- `GET/POST/PUT/DELETE /api/chat-sessions`, plus `/{id}/messages` (`GET/POST`) and `/{id}/messages/{message_id}` (`PUT`) — chat conversations, persisted server-side instead of browser localStorage.
- `GET/POST/PUT/DELETE /api/connections`, plus `/test`, `/discover-schema` (+ `/progress`), `/suggested-questions`, `/tables`, `/tables/{name}`, `/tables/{name}/train`, `/train-all`, `/train-selected`, `/training-jobs`
- `GET/POST/PUT/DELETE /api/sql-examples` (list only returns confirmed/thumbs-up examples)
- `POST /api/ask`, `POST /api/run-sql`, `POST /api/feedback`
- `GET/POST/PUT/DELETE /api/reports`, `POST /api/reports/{id}/run`
- `GET/POST/PUT/DELETE /api/report-schedules`, `GET /api/report-schedules/runs`, `POST /api/report-schedules/{id}/run-now`
- `GET /api/training/stats`, `DELETE /api/training/all`

## Architecture

```
app/
  main.py               FastAPI app + router registration + metadata-DB migration on startup
  models.py             Pydantic request/response schemas (API contract — unchanged)
  store.py              Dict-like façade over the metadata database (connections, reports, schedules, SQL examples, jobs) — persists across restarts
  database.py            SQLAlchemy engine/session + Alembic migration runner for the metadata DB
  db_models.py            SQLAlchemy ORM tables backing store.py
  crypto.py               Encrypts/decrypts saved connection passwords at rest
  logging_config.py       Daily-rotating file logger (7 days) that mirrors everything printed, unchanged
  config.py             Env-based settings (LLM/embedding provider, Qdrant URL, metadata DB, SMTP, token knobs)
  db.py                 Real pymysql connections per DatabaseConnection record (the databases you *chat with*, not the metadata DB)
  schema_introspect.py  Real SHOW TABLES/COLUMNS + tabDocField relationship discovery
  embeddings.py          OpenAI or sentence-transformers, switchable via EMBED_PROVIDER
  llm.py                 OpenAI or Claude, switchable via LLM_PROVIDER
  vector_store.py        Qdrant client — per-connection schema collections + shared SQL-example collection
  guardrail.py            SELECT-only safety check (ported from ask-frappe.py)
  rag.py                  Orchestration: build context -> generate SQL -> guardrail -> execute -> summarize
  email_util.py           Best-effort SMTP delivery for scheduled reports
  routers/               One router per resource, same paths/response models as before
migrations/             Alembic migrations for the metadata database
```
