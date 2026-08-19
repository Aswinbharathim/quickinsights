"""In-process schedule poller — the piece that was missing entirely before:
`ReportSchedule.next_run_at`/`cron_expression` were computed and displayed,
but nothing ever fired a run automatically. This checks every
POLL_INTERVAL_SECONDS for active schedules whose next_run_at has passed and
runs them via the exact same code path as the manual "Run now" button
(app/routers/report_schedules.py's create_schedule_run_row + run_schedule_execution).

No external scheduler library: next_run_at is already computed/stored per
schedule (store.compute_next_run), so this just asks "who's due?" on an
interval instead of re-implementing cron/calendar logic a library would give
for free — reasonable here since that logic already exists in store.py.

Single-process only: running multiple backend workers/replicas would each
poll independently and could double-send the same schedule's email — there's
no distributed lock. Fine for this app's current single-process deployment.

Catch-up behavior: if the backend was down when a schedule's next_run_at
passed, the very first poll after startup finds it overdue and runs it —
oldest-overdue first, one at a time, not concurrently — then computes its
next future occurrence. Nothing scheduled while the backend was down is
silently skipped.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app import store
from app.routers.report_schedules import create_schedule_run_row, run_schedule_execution

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


async def run_due_schedules_once() -> None:
    now = datetime.now(timezone.utc)
    due = []
    for schedule in store.schedule_store.values():
        if not schedule.is_active or not schedule.next_run_at:
            continue
        try:
            next_run = datetime.fromisoformat(schedule.next_run_at)
        except ValueError:
            continue
        if next_run <= now:
            due.append((next_run, schedule))

    due.sort(key=lambda item: item[0])  # oldest-overdue (or most-due) first

    for _next_run, schedule in due:
        try:
            run = create_schedule_run_row(schedule)
            await run_schedule_execution(schedule.id, run.id)
        except Exception as e:
            print(f"Error running due schedule {schedule.id} -- {e}")
            logger.exception("Error running due schedule %s", schedule.id)


async def _scheduler_loop() -> None:
    while True:
        try:
            await run_due_schedules_once()
        except Exception as e:
            print(f"Error in scheduler poll loop -- {e}")
            logger.exception("Error in scheduler poll loop")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def start_scheduler() -> None:
    """Call once, from an async context (main.py's startup handler), after
    the metadata DB is confirmed reachable."""
    asyncio.create_task(_scheduler_loop())
