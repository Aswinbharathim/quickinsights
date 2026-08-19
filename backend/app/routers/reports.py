import logging

from fastapi import APIRouter, HTTPException

from app import store
from app.config import AUTO_LIMIT, MAX_RESULT_ROWS
from app.db import run_select
from app.guardrail import enforce_limit, is_safe_select
from app.models import Report, ReportCreate, ReportRunRequest, ReportRunResult, ReportUpdate
from app.store import new_id_fn, now_fn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[Report])
def list_reports():
    return sorted(store.report_store.values(), key=lambda r: r.created_at, reverse=True)


@router.post("", response_model=Report, status_code=201)
def create_report(payload: ReportCreate):
    new_id = new_id_fn()
    record = Report(id=new_id, created_at=now_fn(), **payload.model_dump())
    store.report_store[new_id] = record
    return record


@router.put("/{report_id}", response_model=Report)
def update_report(report_id: str, payload: ReportUpdate):
    existing = store.report_store.get(report_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Report not found")
    updated = existing.model_copy(update={k: v for k, v in payload.model_dump().items() if v is not None})
    store.report_store[report_id] = updated
    return updated


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: str):
    if report_id not in store.report_store:
        raise HTTPException(status_code=404, detail="Report not found")
    del store.report_store[report_id]
    store.schedule_store.delete_where(lambda s: s.report_id == report_id)
    store.schedule_run_store.delete_where(lambda r: r.report_id == report_id)


@router.post("/{report_id}/run", response_model=ReportRunResult)
def run_report_query(report_id: str, payload: ReportRunRequest):
    """Re-execute the (possibly edited) SQL against the report's live database."""
    report = store.report_store.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if not report.connection_id:
        raise HTTPException(status_code=400, detail="This report has no associated database connection.")
    conn = store.connections_store.get(report.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    ok, reason = is_safe_select(payload.sql)
    if not ok:
        raise HTTPException(status_code=422, detail=f"Query blocked by the safety guardrail: {reason}")
    sql = enforce_limit(payload.sql, AUTO_LIMIT)

    try:
        columns, rows, exec_ms = run_select(conn, sql, MAX_RESULT_ROWS)
    except Exception as e:
        print(f"Error running report query -- {e}")
        logger.exception("Error running report query")
        raise HTTPException(status_code=502, detail=f"Query failed: {e}")

    return ReportRunResult(columns=columns, rows=rows, row_count=len(rows), execution_time_ms=exec_ms)
