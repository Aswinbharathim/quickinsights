"""RAG orchestration: schema training, context retrieval, SQL generation, and
answer synthesis. This is the real equivalent of ask-frappe.py's train_schema /
train_documentation / build_context / generate_sql / suggest_followups /
answer_question, adapted to work per-connection and to feed the QuickInsights
API contract (AskResponse needs both an `explanation` and a `summary`, which
ask-frappe.py didn't split out, so those are produced by two small JSON-mode
LLM calls here). The three training categories (schema / sql_example /
documentation) and the DDL text itself (real `SHOW CREATE TABLE` + slim_ddl)
match ask-frappe.py exactly.
"""
import json
import logging
import re

from app import pricing, store
from app.config import (
    AUTO_LIMIT,
    ENABLE_FOLLOWUPS,
    MAX_RESULT_ROWS,
    SAMPLE_ROWS_FOR_LLM,
    SCHEMA_RELEVANCE_THRESHOLD,
    TOP_K_DOCS,
    TOP_K_EXAMPLES,
    TOP_K_MASTER_DATA,
    TOP_K_SCHEMA,
)
from app.db import get_raw_connection, run_select
from app.embeddings import embed_model_label, embed_one
from app.guardrail import enforce_limit, is_safe_select
from app.llm import llm_generate, provider_and_model_label
from app.sql_permissions import apply_row_filters, referenced_tables
from app.schema_introspect import fetch_table_ddl, slim_ddl
from app.vector_store import (
    collection_name_for_connection,
    delete_point,
    master_data_collection_name_for_connection,
    search,
    sql_examples_collection_name_for_connection,
    upsert_point,
)

logger = logging.getLogger(__name__)

CONVERSATIONAL_INTENTS: list[tuple[list[str], str]] = [
    (
        ["good morning","gud morning","gudmorning"],
        "Good morning! How can I help you?",
    ),
    (
        ["good afternoon","gud afternoon","gudafternoon"],
        "Good afternoon! How can I help you?",
    ),
    (
        ["good evening","gud evening","gudevening"],
        "Good evening! How can I help you?",
    ),
    (
        ["how are you", "how are you doing", "hows it going", "how is it going"],
        "I'm doing well! How can I help you with your data?",
    ),
    (
        ["who are you", "what are you", "who are u", "what is your name", "tell me about yourself", "who is quickinsights"],
        "I am QuickInsights AI, an intelligent assistant designed to help you analyze and query your connected business data using natural language.",
    ),
    (
        ["what can you do", "help", "what can u do", "what can you help me with", "how to use", "how can you help"],
        "I can help you explore your database, generate SQL queries, analyze business data, and answer questions about your connected tables and modules.",
    ),
    (
        ["thanks", "thank you", "thx", "thank u", "many thanks", "thanks a lot"],
        "You're welcome! Let me know if you need anything else.",
    ),
    (
        ["bye", "goodbye", "cya", "see you", "bye bye", "good bye", "have a good day"],
        "Goodbye! Have a great day.",
    ),
    (
        ["hi", "hii","hiii","hiiii","hiiiii","hiiiiii","hello", "hey", "greetings", "hey there", "hello there", "good day", "hi there"],
        "Hello! How can I help you?",
    ),
]

_NONSENSE_RE = re.compile(r"^[^a-zA-Z0-9]+$|^[bcdfghjklmnpqrstvwxyz]{6,}$", re.IGNORECASE)

OUT_OF_DOMAIN_MSG = (
    "This question is outside the available QuickInsights data and business knowledge. "
    "Please ask a question related to the connected database."
)

_QUERY_KEYWORDS = {
    "show", "get", "select", "count", "list", "total", "find", "sum", "average",
    "avg", "min", "max", "where", "table", "doctype", "how many", "which", "recent", "top"
}


def get_conversational_response(question: str) -> str | None:
    """Intercept purely conversational inputs (greetings, time of day, status,
    identity, help, thanks, goodbye) before any vector embedding search or LLM call.

    Returns natural response string if matched, or None if question should proceed to RAG.
    Requires 0 LLM calls, 0 SQL execution, 0 vector store lookups.
    """
    q_trimmed = question.strip().lower()
    q_clean = re.sub(r"[^\w\s]", "", q_trimmed).strip()

    if not q_clean:
        return None

    words = set(q_clean.split())
    if any(k in words for k in _QUERY_KEYWORDS) or "how many" in q_clean:
        return None

    for phrases, response in CONVERSATIONAL_INTENTS:
        for p in phrases:
            if q_clean == p:
                return response
            if re.search(rf"\b{re.escape(p)}\b", q_clean):
                if len(q_clean.split()) <= 6:
                    return response

    return None


def check_out_of_domain(question: str, schema_hits: list[dict], has_exact_example: bool) -> tuple[bool, str]:
    """Layer 1 (Gibberish / Random characters) and Layer 2 (Schema Vector Relevance Score) checks.
    Returns (is_out_of_domain: bool, response_message: str).
    """
    q_trimmed = question.strip().lower()

    # Layer 1: Gibberish / Random characters check
    if len(q_trimmed) > 4 and _NONSENSE_RE.match(q_trimmed):
        return True, OUT_OF_DOMAIN_MSG

    # Layer 2: Schema relevance vector check (skip if exact SQL example matched)
    if not has_exact_example:
        max_schema_score = max((float(h.get("score", 0.0)) for h in schema_hits), default=0.0)
        if schema_hits and max_schema_score < SCHEMA_RELEVANCE_THRESHOLD:
            return True, OUT_OF_DOMAIN_MSG

    return False, ""


def _record_usage(**kwargs) -> None:
    """Fire-and-forget token usage tracking — never let it break the actual
    RAG/training flow it's recording (same convention as the Qdrant upsert
    calls throughout this module)."""
    try:
        store.record_token_usage(**kwargs)
    except Exception as e:
        print(f"Error recording token usage -- {e}")
        logger.exception("Error recording token usage")


# ---------------------------------------------------------------------------
# Training category A — schema: real DDL (SHOW CREATE TABLE + slim_ddl) plus
# relationship hints, embedded per table into that connection's collection.
# ---------------------------------------------------------------------------

def build_table_schema_text(table_name: str, doctype: str, table, ddl: str) -> str:
    lines = [
        f"TABLE: {table_name}  (Frappe DocType: {doctype})",
        "FRAPPE CONVENTION: primary key is always the `name` column — never use `id`. "
        "All Link fields in other tables point to `name`.",
    ]
    if table.description:
        lines.append(f"TABLE DESCRIPTION: {table.description}")

    if table.is_child_table and table.parent_table:
        lines.append(
            "Relationships:\n"
            f"  - CHILD table of `{table.parent_table}` — JOIN: "
            f"`{table_name}`.`parent` = `{table.parent_table}`.`name` "
            f"AND `{table_name}`.`parenttype` = '{table.parent_table[3:]}'"
        )
    elif table.foreign_keys:
        rel_lines = "\n".join(
            f"  - column `{fk.column}` -> `{fk.ref_table}`.`{fk.ref_column}` — JOIN: "
            f"`{table_name}`.`{fk.column}` = `{fk.ref_table}`.`{fk.ref_column}`"
            for fk in table.foreign_keys
        )
        lines.append(f"Relationships:\n{rel_lines}")
    else:
        lines.append("Relationships: none detected.")

    lines.append("DDL:\n" + slim_ddl(ddl))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Training category C — documentation: what a column / its coded values mean,
# embedded separately so it's retrievable on its own (ask-frappe.py option 3).
# ---------------------------------------------------------------------------

def train_column_documentation_now(
    conn_id: str, table_name: str, column: str, data_type: str, description: str, module: str | None = None
) -> None:
    """Documentation lives in the SAME per-connection collection as schema —
    it's a fact about one specific database's columns, unlike SQL examples,
    which are reusable business-question patterns shared across connections."""
    text = (
        f"COLUMN DOC for table `{table_name}`:\n"
        f"  column: {column}\n"
        f"  data type: {data_type}\n"
        f"  meaning: {description}"
    )
    vector, tokens = embed_one(text)
    provider, model = embed_model_label()
    _record_usage(
        connection_id=conn_id, operation="train_column_doc", category="embedding",
        provider=provider, model=model, prompt_tokens=tokens,
    )
    payload = {"category": "documentation", "table": table_name, "column": column}
    if module:
        payload["module"] = module
    upsert_point(
        collection_name_for_connection(conn_id),
        key=f"documentation:{table_name}:{column}",
        text=text,
        vector=vector,
        payload=payload,
    )


def train_table_now(conn_id: str, table_name: str) -> int:
    """Embed one table's real DDL + relationships (category A), plus a
    documentation point (category C) for every column the user has described.
    Returns the total vector count produced."""
    tables = store.tables_store.get(conn_id, {})
    table = tables.get(table_name)
    if not table:
        raise ValueError(f"Table {table_name} not found for connection {conn_id}")

    conn_record = store.connections_store.get(conn_id)
    if not conn_record:
        raise ValueError(f"Connection {conn_id} not found")

    raw_conn = get_raw_connection(conn_record)
    try:
        ddl = fetch_table_ddl(raw_conn, table_name)
    finally:
        raw_conn.close()

    text = build_table_schema_text(table_name, table.doctype, table, ddl)
    vector, tokens = embed_one(text)
    provider, model = embed_model_label()
    _record_usage(
        connection_id=conn_id, operation="train_table", category="embedding",
        provider=provider, model=model, prompt_tokens=tokens,
    )
    payload = {"category": "schema", "table": table_name, "doctype": table.doctype}
    if table.module:
        payload["module"] = table.module
    upsert_point(
        collection_name_for_connection(conn_id),
        key=f"schema:{table_name}",
        text=text,
        vector=vector,
        payload=payload,
    )
    vector_count = 1

    for col in table.columns:
        if col.description:
            train_column_documentation_now(
                conn_id, table_name, col.fieldname, col.fieldtype, col.description, module=table.module
            )
            vector_count += 1

    return vector_count


VERIFIED_QUERY_MARKER = "AUTO-VERIFIED QUERIES (edited & re-run in chat):"
MAX_VERIFIED_QUERY_NOTES = 3


def record_verified_query(conn_id: str, table_name: str, question: str, sql: str) -> None:
    """Append a small note to a table's description when a user edits and
    successfully re-runs a query against it, then re-embed the schema chunk —
    same re-train mechanism `update_table` uses for manual description edits."""
    tables = store.tables_store.get(conn_id, {})
    table = tables.get(table_name)
    if not table:
        return

    base_description, _, rest = (table.description or "").partition(VERIFIED_QUERY_MARKER)
    base_description = base_description.rstrip()
    existing_notes = [line for line in rest.strip().splitlines() if line.startswith("- ")]

    question = (question or "").strip() or "(no question captured)"
    new_note = f"- Q: \"{question}\" -> SQL: {sql.strip()}"
    notes = [new_note] + [n for n in existing_notes if n != new_note]
    notes = notes[:MAX_VERIFIED_QUERY_NOTES]

    new_description = "\n\n".join(
        part for part in (base_description, VERIFIED_QUERY_MARKER + "\n" + "\n".join(notes)) if part
    )

    updated = table.model_copy(update={"description": new_description})
    tables[table_name] = updated
    if updated.training_status == "trained":
        train_table_now(conn_id, table_name)


# ---------------------------------------------------------------------------
# SQL examples: each connection gets its own Qdrant collection
# (qi_sql_examples_<connection_id>), same as schema/docs — every example is
# required to belong to a connection (models.py's SqlExampleBase), so there's
# no shared collection and no payload-filter scoping needed at retrieval
# time; searching a connection's collection IS the scoping.
# ---------------------------------------------------------------------------

def train_sql_example_now(
    example_id: str,
    question: str,
    sql: str,
    connection_id: str,
    description: str = "",
    vote: str = "up",
    module: str | None = None,
) -> None:
    if vote == "down":
        text = f"REJECTED SQL — do NOT reuse this pattern.\nQUESTION: {question}\nSQL THAT WAS MARKED WRONG:\n{sql}"
    else:
        text = f"EXAMPLE QUESTION: {question}\nDESCRIPTION: {description}\nCORRECT SQL:\n{sql}"
    vector, tokens = embed_one(text)
    provider, model = embed_model_label()
    _record_usage(
        connection_id=connection_id, operation="train_sql_example", category="embedding",
        provider=provider, model=model, prompt_tokens=tokens,
    )
    payload = {
        "category": "sql_example", "question": question, "sql": sql,
        "description": description, "vote": vote, "connection_id": connection_id,
    }
    if module:
        payload["module"] = module
    upsert_point(
        sql_examples_collection_name_for_connection(connection_id),
        key=f"sql_example:{example_id}",
        text=text,
        vector=vector,
        payload=payload,
    )


def delete_sql_example_vector(example_id: str, connection_id: str) -> None:
    delete_point(sql_examples_collection_name_for_connection(connection_id), key=f"sql_example:{example_id}")


# ---------------------------------------------------------------------------
# Master data: real reference/lookup-table row data (e.g. an actual Category
# or Status table's rows), one collection per connection
# (qi_master_data_<connection_id>), same "own collection per connection"
# design as SQL examples — so the LLM can resolve a name mentioned in a
# question (e.g. "Electronics") to the real value/id it maps to in that
# table, instead of guessing a literal that doesn't exist.
# ---------------------------------------------------------------------------

def build_master_data_text(table_name: str, row_data: dict[str, str]) -> str:
    fields = "; ".join(f"{col}: {val}" for col, val in row_data.items())
    return f"MASTER DATA ROW — table `{table_name}`: {fields}"


def train_master_data_row_now(
    record_id: str,
    connection_id: str,
    table_name: str,
    row_data: dict[str, str],
    module: str | None = None,
) -> None:
    text = build_master_data_text(table_name, row_data)
    vector, tokens = embed_one(text)
    provider, model = embed_model_label()
    _record_usage(
        connection_id=connection_id, operation="train_master_data", category="embedding",
        provider=provider, model=model, prompt_tokens=tokens,
    )
    payload = {"category": "master_data", "table": table_name, "row_data": row_data}
    if module:
        payload["module"] = module
    upsert_point(
        master_data_collection_name_for_connection(connection_id),
        key=f"master_data:{record_id}",
        text=text,
        vector=vector,
        payload=payload,
    )


def delete_master_data_vector(record_id: str, connection_id: str) -> None:
    delete_point(master_data_collection_name_for_connection(connection_id), key=f"master_data:{record_id}")


# ---------------------------------------------------------------------------
# Question answering pipeline
# ---------------------------------------------------------------------------

def build_context(
    conn_id: str, question: str, module: str | None = None, allowed_tables: list[str] | None = None
) -> tuple[str, list[dict], int]:
    """allowed_tables, when not None, is a Frappe-resolved permission scope
    (see app/frappe_auth.py) -- schema hits for any other table are dropped
    BEFORE the LLM ever sees them, so a restricted user's SQL generation
    never has a disallowed table's schema in its prompt context at all.
    None means unrestricted (standalone mode, or a Frappe user with no
    table restriction) -- an empty list would mean "no tables allowed."""
    vector, embed_tokens = embed_one(question)
    embed_provider, embed_model = embed_model_label()
    _record_usage(
        connection_id=conn_id, operation="ask_embedding", category="embedding",
        provider=embed_provider, model=embed_model, prompt_tokens=embed_tokens,
    )
    collection = collection_name_for_connection(conn_id)
    sql_examples_collection = sql_examples_collection_name_for_connection(conn_id)
    master_data_collection = master_data_collection_name_for_connection(conn_id)
    schema_hits = search(collection, vector, TOP_K_SCHEMA, category="schema", module=module)
    doc_hits = search(collection, vector, TOP_K_DOCS, category="documentation", module=module)
    example_hits = search(
        sql_examples_collection, vector, TOP_K_EXAMPLES,
        category="sql_example", vote="up", module=module,
    )
    rejected_hits = search(
        sql_examples_collection, vector, TOP_K_EXAMPLES,
        category="sql_example", vote="down", module=module,
    )
    master_data_hits = search(
        master_data_collection, vector, TOP_K_MASTER_DATA, category="master_data", module=module,
    )

    # Fallback to unrestricted search if module filter produced no schema hits.
    # This only ever drops the module filter — the connection itself is
    # already fixed by which collection is being searched, so there's
    # nothing left to relax there.
    if module and not schema_hits:
        schema_hits = search(collection, vector, TOP_K_SCHEMA, category="schema")
        doc_hits = search(collection, vector, TOP_K_DOCS, category="documentation")
        example_hits = search(sql_examples_collection, vector, TOP_K_EXAMPLES, category="sql_example", vote="up")
        rejected_hits = search(sql_examples_collection, vector, TOP_K_EXAMPLES, category="sql_example", vote="down")
        master_data_hits = search(master_data_collection, vector, TOP_K_MASTER_DATA, category="master_data")

    if allowed_tables is not None:
        allowed = set(allowed_tables)
        schema_hits = [h for h in schema_hits if h.get("table") in allowed]
        doc_hits = [h for h in doc_hits if h.get("table") in allowed]
        master_data_hits = [h for h in master_data_hits if h.get("table") in allowed]

    parts = []
    if schema_hits:
        parts.append("### RELEVANT TABLES (schema + relationships)\n" + "\n\n".join(h["text"] for h in schema_hits))
    if doc_hits:
        parts.append("### COLUMN DOCUMENTATION\n" + "\n\n".join(h["text"] for h in doc_hits))
    if master_data_hits:
        parts.append(
            "### KNOWN REFERENCE / MASTER DATA VALUES (real rows from lookup tables — use these to resolve "
            "a name mentioned in the question to its actual id/value instead of guessing a literal)\n"
            + "\n\n".join(h["text"] for h in master_data_hits)
        )
    if example_hits:
        parts.append(
            "### REFERENCE SOLVED EXAMPLES (Use as reference patterns for joins, tables, columns, filters, and business logic — generate new SQL specifically for the current user question)\n"
            + "\n\n".join(h["text"] for h in example_hits)
        )
    if rejected_hits:
        parts.append(
            "### PREVIOUSLY REJECTED SQL FOR SIMILAR QUESTIONS — do NOT repeat these patterns\n"
            + "\n\n".join(h["text"] for h in rejected_hits)
        )
    return "\n\n".join(parts), schema_hits, embed_tokens


SQL_SYSTEM_PROMPT = (
    "You are an expert MariaDB analyst for a Frappe ERPNext database. "
    "Frappe data tables are named `tab<DocType>` (note the spaces, so always "
    "backtick-quote them, e.g. `tabSales Order`). "
    "First, determine if the question is a COMPLETELY UNRELATED NON-DATABASE TOPIC (e.g. greetings, jokes, general knowledge, recipes, weather, non-business chat). "
    "If and only if it is a completely unrelated non-database topic, respond with ONLY a JSON object: "
    '{"out_of_domain": true, "explanation": "This question is outside the available QuickInsights data and business knowledge. Please ask a question related to the connected database.", "sql": ""}. '
    "Otherwise, for ANY business or database question (patients, doctors, appointments, sales, billing, counts, totals, etc.), set \"out_of_domain\": false "
    "and write ONE valid MariaDB SELECT query using ONLY the tables/columns in the provided context, plus a one-sentence explanation for a non-technical reader. "
    "Never write INSERT/UPDATE/DELETE/DDL. "
    "When REFERENCE SOLVED EXAMPLES are present, use them as reference patterns to understand how similar business questions were solved (including joins, tables, columns, filters, and query logic), and generate a NEW SQL query tailored specifically to the current question. Do not copy them blindly if the current question asks for different parameters or entities. "
    "If a PREVIOUSLY REJECTED SQL section is present, do not reproduce that query or its mistake for a similar question. "
    'Respond with ONLY a JSON object of the shape {"out_of_domain": false, "sql": "...", "explanation": "..."} '
    "— no markdown fences, no extra text."
)

FOLLOWUP_SYSTEM_PROMPT = (
    "You summarize SQL query results for a business user in 1-2 sentences (cite "
    "concrete numbers from the sample rows when possible), and suggest exactly 3 "
    "insightful follow-up questions the user might ask next. "
    'Respond with ONLY a JSON object {"summary": "...", "follow_up_questions": ["...", "...", "..."]} '
    "— no markdown fences, no extra text."
)


def _strip_fences(text: str) -> str:
    return text.replace("```json", "").replace("```sql", "").replace("```", "").strip()


def generate_sql_and_explanation(question: str, context: str, conn_id: str | None = None) -> tuple[str, str, bool, int, int]:
    user = f"{context}\n\n### QUESTION\n{question}\n\n### RESPONSE (JSON)"
    raw, prompt_tokens, completion_tokens = llm_generate(SQL_SYSTEM_PROMPT, user)
    provider, model = provider_and_model_label()
    _record_usage(
        connection_id=conn_id, operation="ask_sql_generation", category="llm",
        provider=provider, model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
    )
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        is_ood = bool(data.get("out_of_domain", False))
        sql = (data.get("sql") or "").strip()
        explanation = (data.get("explanation") or "").strip()
        if is_ood or not sql:
            return "", explanation or OUT_OF_DOMAIN_MSG, True, prompt_tokens, completion_tokens
    except Exception as e:
        print(f"Error parsing SQL generation response -- {e}")
        logger.exception("Error parsing SQL generation response")
        sql = raw
        explanation = "Generated SQL query for your question."
        is_ood = False
    return sql, explanation, is_ood, prompt_tokens, completion_tokens


def generate_summary_and_followups(
    question: str, sql: str, columns: list[str], rows: list[dict],
    conn_id: str | None = None, operation: str = "ask_summary",
):
    if not ENABLE_FOLLOWUPS:
        return "", [], 0, 0

    sample = rows[:SAMPLE_ROWS_FOR_LLM]
    user = (
        f"Original question: {question}\nSQL used: {sql}\nResult columns: {columns}\n"
        f"Sample rows: {json.dumps(sample, default=str)}\nTotal rows returned: {len(rows)}"
    )
    raw, prompt_tokens, completion_tokens = llm_generate(FOLLOWUP_SYSTEM_PROMPT, user)
    provider, model = provider_and_model_label()
    _record_usage(
        connection_id=conn_id, operation=operation, category="llm",
        provider=provider, model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
    )
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        summary = data.get("summary") or ""
        follow_ups = data.get("follow_up_questions") or []
    except Exception as e:
        print(f"Error parsing summary/follow-ups response -- {e}")
        logger.exception("Error parsing summary/follow-ups response")
        summary = raw
        follow_ups = []
    return summary, follow_ups, prompt_tokens, completion_tokens


SUGGESTED_QUESTIONS_SYSTEM_PROMPT = (
    "You are helping a business user get started chatting with their database. "
    "Given a list of that database's trained tables (and descriptions where available), "
    "suggest exactly 4 short, concrete example questions a business user could ask in "
    "plain English. Favor questions that aggregate or rank data (totals, top N, counts, "
    "recent activity) over trivial single-row lookups, and only reference tables/concepts "
    "actually present in the list. "
    'Respond with ONLY a JSON object {"questions": ["...", "...", "...", "..."]} '
    "— no markdown fences, no extra text."
)


def generate_suggested_questions(conn_id: str) -> list[str]:
    """Starter questions shown on an empty chat, tailored to what's actually
    trained for this connection — unlike the per-answer follow-ups, this runs
    with no question/result context yet, just the trained table list."""
    tables = store.tables_store.get(conn_id, {})
    trained = [t for t in tables.values() if t.training_status == "trained"]
    if not trained:
        return []

    lines = []
    for t in trained[:30]:
        desc = f" — {t.description}" if t.description else ""
        lines.append(f"- {t.table_name} (DocType: {t.doctype}){desc}")
    user = "TRAINED TABLES:\n" + "\n".join(lines)

    raw, prompt_tokens, completion_tokens = llm_generate(SUGGESTED_QUESTIONS_SYSTEM_PROMPT, user)
    provider, model = provider_and_model_label()
    _record_usage(
        connection_id=conn_id, operation="suggested_questions", category="llm",
        provider=provider, model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
    )
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
        questions = data.get("questions") or []
    except Exception as e:
        print(f"Error parsing suggested questions response -- {e}")
        logger.exception("Error parsing suggested questions response")
        questions = []
    return questions[:4]


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    return pricing.estimate_cost_usd(model, prompt_tokens, completion_tokens)


def answer_question(
    conn_record,
    conn_id: str,
    question: str,
    module: str | None = None,
    allowed_tables: list[str] | None = None,
    row_filters: dict[str, dict[str, list[str]]] | None = None,
) -> dict:
    """Full retrieve -> generate -> guardrail -> execute -> summarize pipeline.

    allowed_tables/row_filters come only from a verified Frappe Identity
    (app/frappe_auth.py) -- never from the request body. allowed_tables
    restricts which tables' schema the LLM even sees (see build_context);
    row_filters is enforced deterministically on the generated SQL, after
    the guardrail and before execution (see app/sql_permissions.py). Both
    None (the default) reproduces today's fully unrestricted behavior.

    Raises LookupError if there's no trained context, PermissionError if the
    guardrail (or the permission filter) blocks the generated SQL, or lets
    DB/LLM exceptions bubble up.
    """
    # Step 0: Conversational intent check BEFORE any vector search or LLM call
    conv_response = get_conversational_response(question)
    if conv_response:
        return {
            "sql": "",
            "explanation": conv_response,
            "summary": "",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": 0,
            "follow_up_questions": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    # Step 1: Build RAG context (semantic retrieval in Qdrant for schema, docs, and SQL examples)
    context, schema_hits, embed_tokens = build_context(conn_id, question, module=module, allowed_tables=allowed_tables)
    if not context:
        raise LookupError("No trained schema found for this connection yet.")

    # Step 2: Out-of-Domain checks (Gibberish & Low Schema Relevance)
    is_ood, ood_msg = check_out_of_domain(question, schema_hits, has_exact_example=False)
    if is_ood:
        return {
            "sql": "",
            "explanation": ood_msg,
            "summary": "",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": 0,
            "follow_up_questions": [],
            "prompt_tokens": embed_tokens,
            "completion_tokens": 0,
        }

    # Step 3: LLM SQL Generation using semantic context & reference SQL examples
    sql, explanation, is_ood_llm, p1, c1 = generate_sql_and_explanation(question, context, conn_id=conn_id)
    if is_ood_llm or not sql:
            return {
                "sql": "",
                "explanation": explanation or OUT_OF_DOMAIN_MSG,
                "summary": "",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0,
                "follow_up_questions": [],
                "prompt_tokens": embed_tokens + p1,
                "completion_tokens": c1,
            }

    ok, reason = is_safe_select(sql)
    if not ok:
        raise PermissionError(reason)
    sql = enforce_limit(sql, AUTO_LIMIT)

    # Deterministic, non-LLM permission enforcement -- see app/sql_permissions.py.
    # Belt-and-suspenders: even though build_context already hid disallowed
    # tables' schema from the LLM, this catches the LLM referencing one
    # anyway (e.g. from a stale few-shot example) and blocks outright rather
    # than trying to filter rows out of a table the user can't read at all.
    if allowed_tables is not None:
        disallowed = referenced_tables(sql) - set(allowed_tables)
        if disallowed:
            raise PermissionError(
                f"Generated query references table(s) outside your permitted scope: {', '.join(sorted(disallowed))}"
            )
    if row_filters:
        sql = apply_row_filters(sql, row_filters)

    columns, rows, exec_ms = run_select(conn_record, sql, MAX_RESULT_ROWS)

    summary, follow_ups, p2, c2 = generate_summary_and_followups(question, sql, columns, rows, conn_id=conn_id)

    return {
        "sql": sql,
        "explanation": explanation,
        "summary": summary,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "execution_time_ms": exec_ms,
        "follow_up_questions": follow_ups,
        "prompt_tokens": embed_tokens + p1 + p2,
        "completion_tokens": c1 + c2,
    }

