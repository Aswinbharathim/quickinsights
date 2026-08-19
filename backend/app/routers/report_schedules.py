import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app import store
from app.config import AUTO_LIMIT, MAX_RESULT_ROWS
from app.db import run_select
from app.email_util import send_email
from app.guardrail import enforce_limit, is_safe_select
from app.models import ReportSchedule, ReportScheduleCreate, ReportScheduleUpdate, ScheduleRun
from app.store import new_id_fn, now_fn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/report-schedules", tags=["report-schedules"])


@router.get("", response_model=list[ReportSchedule])
def list_schedules():
    return sorted(store.schedule_store.values(), key=lambda s: s.created_at, reverse=True)


@router.get("/runs", response_model=list[ScheduleRun])
def list_all_runs():
    return sorted(store.schedule_run_store.values(), key=lambda r: r.started_at, reverse=True)


@router.post("", response_model=ReportSchedule, status_code=201)
def create_schedule(payload: ReportScheduleCreate):
    if payload.report_id not in store.report_store:
        raise HTTPException(status_code=404, detail="Report not found")
    new_id = new_id_fn()
    data = payload.model_dump()
    schedule = ReportSchedule(
        id=new_id,
        created_at=now_fn(),
        cron_expression=store.compute_cron_expression(
            data["frequency"], data["time_of_day"], data["day_of_week"], data["day_of_month"]
        ),
        next_run_at=store.compute_next_run(
            data["frequency"],
            data["time_of_day"],
            data["day_of_week"],
            data["day_of_month"],
            datetime.now(timezone.utc),
            tz_name=data["timezone"],
        ),
        **data,
    )
    store.schedule_store[new_id] = schedule
    return schedule


@router.put("/{schedule_id}", response_model=ReportSchedule)
def update_schedule(schedule_id: str, payload: ReportScheduleUpdate):
    existing = store.schedule_store.get(schedule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found")
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = existing.model_copy(update=changes)

    if any(k in changes for k in ("frequency", "time_of_day", "timezone", "day_of_week", "day_of_month")):
        updated = updated.model_copy(
            update={
                "cron_expression": store.compute_cron_expression(
                    updated.frequency, updated.time_of_day, updated.day_of_week, updated.day_of_month
                ),
                "next_run_at": store.compute_next_run(
                    updated.frequency,
                    updated.time_of_day,
                    updated.day_of_week,
                    updated.day_of_month,
                    datetime.now(timezone.utc),
                    tz_name=updated.timezone,
                ),
            }
        )

    store.schedule_store[schedule_id] = updated
    return updated


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str):
    if schedule_id not in store.schedule_store:
        raise HTTPException(status_code=404, detail="Schedule not found")
    del store.schedule_store[schedule_id]
    store.schedule_run_store.delete_where(lambda r: r.schedule_id == schedule_id)


def create_schedule_run_row(schedule: ReportSchedule) -> ScheduleRun:
    """Shared by the manual "Run now" endpoint and app/scheduler.py's
    automatic poller — both need an identical ScheduleRun row created before
    kicking off run_schedule_execution.

    Also CLAIMS this occurrence right here, before any actual execution: it
    advances the schedule's next_run_at/last_run_at immediately, rather than
    after the send completes. This is deliberate — if the backend crashes at
    any point after this call (including mid-send, or even after a
    successful send but before the old code would've recorded that), a
    restart's catch-up poll will no longer see this occurrence as still due,
    so it can never send a duplicate email. The trade-off: a send that
    genuinely fails is not auto-retried for this occurrence — it's recorded
    in run history (status="failed") for a manual "Run now" instead of being
    silently retried into a false "we already know it failed" duplicate."""
    run = ScheduleRun(
        id=new_id_fn(),
        schedule_id=schedule.id,
        report_id=schedule.report_id,
        status="running",
        started_at=now_fn(),
        recipients=schedule.recipient_emails,
    )
    store.schedule_run_store[run.id] = run

    store.schedule_store[schedule.id] = schedule.model_copy(
        update={
            "last_run_at": run.started_at,
            "next_run_at": store.compute_next_run(
                schedule.frequency,
                schedule.time_of_day,
                schedule.day_of_week,
                schedule.day_of_month,
                datetime.now(timezone.utc),
                tz_name=schedule.timezone,
            ),
        }
    )
    return run


async def run_schedule_execution(schedule_id: str, run_id: str):
    run = store.schedule_run_store.get(run_id)
    schedule = store.schedule_store.get(schedule_id)
    if not run or not schedule:
        return

    status = "failed"
    row_count = None
    error = None
    try:
        report = store.report_store.get(schedule.report_id)
        if not report or not report.connection_id:
            raise RuntimeError("Report has no associated database connection")
        conn = store.connections_store.get(report.connection_id)
        if not conn:
            raise RuntimeError("Connection not found")

        ok, reason = is_safe_select(report.sql)
        if not ok:
            raise RuntimeError(f"Query blocked by the safety guardrail: {reason}")
        sql = enforce_limit(report.sql, AUTO_LIMIT)

        columns, rows, _exec_ms = await asyncio.to_thread(run_select, conn, sql, MAX_RESULT_ROWS)
        row_count = len(rows)

        await asyncio.to_thread(
            send_email,
            schedule.recipient_emails,
            f"Scheduled report: {report.title}",
            f"'{report.title}' ran successfully with {row_count} row(s).\n\n{report.description or ''}",
        )
        status = "success"
    except Exception as e:
        print(f"Error running scheduled report {schedule_id} -- {e}")
        logger.exception("Error running scheduled report %s", schedule_id)
        error = str(e)

    completed_at = now_fn()
    update = {"status": status, "completed_at": completed_at, "row_count": row_count}
    if error:
        update["error"] = error
    store.schedule_run_store[run_id] = run.model_copy(update=update)
    # next_run_at/last_run_at were already claimed in create_schedule_run_row,
    # BEFORE this execution started — see its docstring for why.


@router.post("/{schedule_id}/run-now", response_model=ScheduleRun, status_code=202)
async def run_schedule_now(schedule_id: str):
    schedule = store.schedule_store.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    run = create_schedule_run_row(schedule)
    asyncio.create_task(run_schedule_execution(schedule_id, run.id))
    return run
