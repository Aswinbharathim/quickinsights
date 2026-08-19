"""
Runtime configuration for the real RAG backend.
All values are read from environment variables / a `.env` file (see .env.example).
Per-database credentials (host/user/password/etc.) are NOT here — those live in
each DatabaseConnection record created through the UI, since this backend
supports connecting to multiple different databases at once.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ---- LLM provider ----------------------------------------------------------
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")  # "openai" or "anthropic"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# ---- Embedding provider -----------------------------------------------------
EMBED_PROVIDER = os.environ.get("EMBED_PROVIDER", "openai")  # "openai" or "sentence-transformers"
OPENAI_EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
ST_EMBED_MODEL = os.environ.get("ST_EMBED_MODEL", "all-MiniLM-L6-v2")

_DEFAULT_DIM = "384" if EMBED_PROVIDER == "sentence-transformers" else "1536"
EMBED_DIM = int(os.environ.get("EMBED_DIM", "") or _DEFAULT_DIM)

# ---- Vector store (Qdrant) --------------------------------------------------
# Docker URL (see docker-compose.yml). Leave blank to fall back to embedded on-disk mode.
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

# ---- App metadata database (MariaDB, separate from any user database) ------
# Persists connections/reports/schedules/SQL examples/training state so they
# survive a backend restart. Same MariaDB version Frappe recommends (10.6 LTS,
# upgradable to 10.11/11.x) — see docker-compose.yml's `mariadb` service.
# Set METADATA_DATABASE_URL directly to point at an existing MariaDB server
# instead of the pieces below.
METADATA_DB_HOST = os.environ.get("METADATA_DB_HOST", "localhost")
METADATA_DB_PORT = int(os.environ.get("METADATA_DB_PORT", "3307"))
METADATA_DB_NAME = os.environ.get("METADATA_DB_NAME", "quickinsights")
METADATA_DB_USER = os.environ.get("METADATA_DB_USER", "quickinsights")
METADATA_DB_PASSWORD = os.environ.get("METADATA_DB_PASSWORD", "quickinsights")
METADATA_DATABASE_URL = os.environ.get("METADATA_DATABASE_URL") or (
    f"mysql+pymysql://{METADATA_DB_USER}:{METADATA_DB_PASSWORD}"
    f"@{METADATA_DB_HOST}:{METADATA_DB_PORT}/{METADATA_DB_NAME}?charset=utf8mb4"
)

# Fernet key used to encrypt saved DatabaseConnection passwords at rest in the
# metadata database. Generate one with:
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Leave blank only for local/throwaway dev — passwords are then stored as
# plain text, same as before this database existed.
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

# ---- Retrieval / token knobs -------------------------------------------------
TOP_K_SCHEMA = int(os.environ.get("TOP_K_SCHEMA", "3"))
TOP_K_EXAMPLES = int(os.environ.get("TOP_K_EXAMPLES", "2"))
TOP_K_DOCS = int(os.environ.get("TOP_K_DOCS", "2"))
TOP_K_MASTER_DATA = int(os.environ.get("TOP_K_MASTER_DATA", "3"))
MAX_RESULT_ROWS = int(os.environ.get("MAX_RESULT_ROWS", "200"))
AUTO_LIMIT = int(os.environ.get("AUTO_LIMIT", "500"))
SAMPLE_ROWS_FOR_LLM = int(os.environ.get("SAMPLE_ROWS_FOR_LLM", "3"))
ENABLE_FOLLOWUPS = os.environ.get("ENABLE_FOLLOWUPS", "true").lower() == "true"
SCHEMA_RELEVANCE_THRESHOLD = float(os.environ.get("SCHEMA_RELEVANCE_THRESHOLD", "0.22"))

# Rough per-1K-token cost used only to populate the UI's estimated_cost_usd field.
OPENAI_COST_PER_1K_INPUT = float(os.environ.get("OPENAI_COST_PER_1K_INPUT", "0.00015"))
OPENAI_COST_PER_1K_OUTPUT = float(os.environ.get("OPENAI_COST_PER_1K_OUTPUT", "0.0006"))

# ---- Optional: limit schema discovery scope ---------------------------------
# Comma-separated DocType names — ported directly from ask-frappe.py's
# DOCTYPE_FILTER. Leave blank to introspect ALL `tab*` tables. Handy for
# testing against a large site without burning embedding/LLM tokens training
# hundreds of tables you don't care about. Remove/blank it out to go back to
# discovering everything.
DOCTYPE_FILTER = [d.strip() for d in os.environ.get("DOCTYPE_FILTER", "").split(",") if d.strip()]

# ---- Frappe identity bridge (optional) --------------------------------------
# Comma-separated shared secret(s) used to verify signed identity tokens
# minted by the QuickInsights Frappe app's whitelisted get_identity_token
# method (see app/frappe_auth.py). Supports rotation -- list an old + new
# secret together while a site's QuickInsights Settings secret is being
# rotated, and either will verify. Leave blank (the default) and every
# request behaves exactly as standalone QuickInsights does today -- this
# whole bridge is purely additive, never a requirement.
QUICKINSIGHTS_SIGNING_SECRETS = [
    s.strip() for s in os.environ.get("QUICKINSIGHTS_SIGNING_SECRETS", "").split(",") if s.strip()
]

# ---- Optional: scheduled report emails --------------------------------------
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")
