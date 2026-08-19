import logging

from fastapi import APIRouter, Depends, HTTPException

from app import rag, store
from app.config import AUTO_LIMIT, MAX_RESULT_ROWS
from app.db import run_select
from app.frappe_auth import Identity, get_identity
from app.guardrail import enforce_limit, is_safe_select
from app.llm import model_label
from app.models import (
    AskRequest,
    AskResponse,
    FeedbackRequest,
    QueryResult,
    RunSqlRequest,
    RunSqlResponse,
    SqlExample,
    TokenUsage,
)
from app.sql_permissions import apply_row_filters, referenced_tables
from app.store import new_id_fn, now_fn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _referenced_table_names(sql: str) -> set[str]:
    return referenced_tables(sql)


@router.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest, identity: Identity | None = Depends(get_identity)):
    if not payload.connection_id:
        raise HTTPException(status_code=400, detail="Select a database connection before asking a question.")

    conn = store.connections_store.get(payload.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    tables = store.tables_store.get(payload.connection_id, {})
    if not any(t.training_status == "trained" for t in tables.values()):
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{conn.name}' has no trained tables yet. "
                "Train at least one table in Connections before asking questions."
            ),
        )

    # identity is None in standalone (unauthenticated) mode -- that reproduces
    # today's fully unrestricted behavior exactly. When it IS present, its
    # allowed_tables/row_filters came only from a signature-verified token
    # (see app/frappe_auth.py), never from this request.
    try:
        result = rag.answer_question(
            conn,
            payload.connection_id,
            payload.question,
            module=payload.module,
            allowed_tables=identity.allowed_tables if identity else None,
            row_filters=identity.row_filters if identity else None,
        )
    except LookupError as e:
        print(f"Error answering question -- no trained context -- {e}")
        logger.warning("Error answering question -- no trained context -- %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        print(f"Error answering question -- guardrail blocked generated SQL -- {e}")
        logger.warning("Error answering question -- guardrail blocked generated SQL -- %s", e)
        raise HTTPException(status_code=422, detail=f"Generated SQL was blocked by the safety guardrail: {e}")
    except Exception as e:
        print(f"Error answering question -- {e}")
        logger.exception("Error answering question")
        raise HTTPException(status_code=502, detail=f"Query failed: {e}")

    total_tokens = result["prompt_tokens"] + result["completion_tokens"]

    return AskResponse(
        message_id=new_id_fn(),
        question=payload.question,
        sql=result["sql"],
        explanation=result["explanation"],
        summary=result["summary"],
        result=QueryResult(
            columns=result["columns"],
            rows=result["rows"],
            row_count=result["row_count"],
            execution_time_ms=result["execution_time_ms"],
        ),
        token_usage=TokenUsage(
            prompt_tokens=result["prompt_tokens"],
            completion_tokens=result["completion_tokens"],
            total_tokens=total_tokens,
            estimated_cost_usd=rag.estimate_cost_usd(model_label(), result["prompt_tokens"], result["completion_tokens"]),
        ),
        follow_up_questions=result["follow_up_questions"],
        model_used=model_label(),
        generated_at=now_fn(),
        connection_id=payload.connection_id,
        connection_name=conn.name,
    )


@router.post("/run-sql", response_model=RunSqlResponse)
def run_edited_sql(payload: RunSqlRequest, identity: Identity | None = Depends(get_identity)):
    """Re-execute a user-edited query from a chat message against its connection —
    same guardrail + execution path as the reports "Run query" preview, just not
    tied to a saved report yet. Also regenerates the summary/follow-ups so they stay
    consistent with the (possibly different) results the edited SQL now returns.

    This is USER-SUPPLIED SQL, not LLM-generated -- so when a Frappe identity
    is present, it gets exactly the same allowed_tables/row_filters
    enforcement as the /ask path (below). Without this, a signed-in user
    could bypass every permission restriction just by hand-editing the SQL
    in the chat UI instead of asking a question."""
    conn = store.connections_store.get(payload.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    ok, reason = is_safe_select(payload.sql)
    if not ok:
        raise HTTPException(status_code=422, detail=f"Query blocked by the safety guardrail: {reason}")
    sql = enforce_limit(payload.sql, AUTO_LIMIT)

    if identity and identity.allowed_tables is not None:
        disallowed = referenced_tables(sql) - set(identity.allowed_tables)
        if disallowed:
            raise HTTPException(
                status_code=403,
                detail=f"Query references table(s) outside your permitted scope: {', '.join(sorted(disallowed))}",
            )
    if identity and identity.row_filters:
        try:
            sql = apply_row_filters(sql, identity.row_filters)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))

    try:
        columns, rows, exec_ms = run_select(conn, sql, MAX_RESULT_ROWS)
    except Exception as e:
        print(f"Error running edited SQL -- {e}")
        logger.exception("Error running edited SQL")
        raise HTTPException(status_code=502, detail=f"Query failed: {e}")

    summary, follow_ups, _p, _c = rag.generate_summary_and_followups(
        payload.question or "Re-run the edited query.", sql, columns, rows,
        conn_id=payload.connection_id, operation="run_sql_summary",
    )

    trained_tables = store.tables_store.get(payload.connection_id, {})
    for table_name in _referenced_table_names(sql):
        if table_name in trained_tables:
            try:
                rag.record_verified_query(payload.connection_id, table_name, payload.question or "", sql)
            except Exception as e:
                print(f"Error recording verified query for table {table_name} -- {e}")
                logger.exception("Error recording verified query for table %s", table_name)
                # schema re-embedding is supplementary — don't fail the query run

    return RunSqlResponse(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=exec_ms,
        summary=summary,
        follow_up_questions=follow_ups,
    )


def _find_feedback_example(message_id: str) -> SqlExample | None:
    """At most one feedback-sourced SqlExample can exist per chat message —
    submit_feedback below enforces that by updating this one in place rather
    than ever inserting a second row for the same message_id."""
    for ex in store.sql_example_store.values():
        if ex.source == "feedback" and ex.source_message_id == message_id:
            return ex
    return None


@router.post("/feedback", response_model=SqlExample, status_code=201)
def submit_feedback(payload: FeedbackRequest):
    """Save a Q->SQL pair from chat feedback. Thumbs-up saves it as a reusable
    few-shot example; thumbs-down saves it as a "don't repeat this" signal —
    both are embedded so retrieval can act on them, neither shows up in the
    manual /api/sql-examples list (that stays confirmed-examples only).

    Idempotent per message_id: re-voting the same message (whether re-
    clicking the same thumb — e.g. a double-click before the UI updates —
    or switching from thumbs-up to thumbs-down) updates the ONE existing
    feedback example for this message in place instead of inserting a new
    row every time. Previously this always inserted, so repeated clicks
    silently piled up duplicate training examples for the exact same
    question/SQL pair."""
    vote = "up" if payload.is_correct else "down"
    # The feedback request itself doesn't carry a connection_id, but the chat
    # message it's about does (via its saved AskResponse) — reuse that so
    # feedback-sourced examples get scoped the same as manually-added ones.
    # There's no "global" fallback anymore, so if this can't be resolved the
    # feedback simply can't be saved as a training example.
    source_message = store.get_chat_message(payload.message_id)
    connection_id = source_message.ask.connection_id if source_message and source_message.ask else None
    if not connection_id:
        raise HTTPException(
            status_code=400,
            detail="Could not resolve the connection for this message — feedback was not saved as a training example.",
        )
    existing = _find_feedback_example(payload.message_id)
    record_id = existing.id if existing else new_id_fn()
    record = SqlExample(
        id=record_id,
        question=payload.question,
        sql=payload.sql,
        connection_id=connection_id,
        tags=["from-feedback"] if payload.is_correct else ["from-feedback", "rejected"],
        created_at=existing.created_at if existing else now_fn(),
        source="feedback",
        vote=vote,
        # Only set when the message actually resolved — an FK to a
        # nonexistent id would just fail at the DB layer anyway.
        source_message_id=source_message.id if source_message else None,
    )
    store.sql_example_store[record_id] = record
    try:
        # Reuses the same record_id, so this is an upsert (same Qdrant point
        # key) when updating an existing vote, not a second point.
        rag.train_sql_example_now(record_id, payload.question, payload.sql, vote=vote, connection_id=connection_id)
    except Exception as e:
        print(f"Error embedding feedback example {record_id} -- {e}")
        logger.exception("Error embedding feedback example %s", record_id)
        # vector store hiccup shouldn't block saving the example itself
    return record


@router.delete("/feedback/{message_id}", status_code=204)
def clear_feedback(message_id: str):
    """Toggling the same thumbs icon again clears feedback entirely, rather
    than only ever being replaceable by voting the opposite way — deletes
    the backing SqlExample + its Qdrant vector (if one exists) and resets
    the source chat message's feedback field back to neutral in the same
    call, mirroring what deleting a feedback-sourced example from the SQL
    Examples page already does (routers/sql_examples.py's
    delete_sql_example), just triggered from the chat icon instead."""
    existing = _find_feedback_example(message_id)
    if existing:
        del store.sql_example_store[existing.id]
        try:
            rag.delete_sql_example_vector(existing.id, existing.connection_id)
        except Exception as e:
            print(f"Error deleting feedback example vector {existing.id} -- {e}")
            logger.exception("Error deleting feedback example vector %s", existing.id)
    try:
        store.clear_chat_message_feedback(message_id)
    except Exception as e:
        print(f"Error clearing feedback on chat message {message_id} -- {e}")
        logger.exception("Error clearing feedback on chat message %s", message_id)
