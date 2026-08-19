import asyncio
import logging
import time

from app.logging_config import reassert_root_logging, setup_logging

setup_logging()  # first thing, before anything else has a chance to print

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

from app.database import run_migrations
from app.routers import (
    chat,
    chat_sessions,
    connections,
    master_data,
    report_schedules,
    reports,
    settings,
    sql_examples,
    training,
    usage,
)
from app.scheduler import start_scheduler

app = FastAPI(
    title="QuickInsights RAG SQL API",
    description="FastAPI backend for the Chat-with-your-Database RAG UI. "
    "Backed by real MariaDB/MySQL/Postgres connections, a real Qdrant vector "
    "store, and a real LLM (OpenAI or Claude) for SQL generation.",
    version="1.0.0",
)

from fastapi.responses import JSONResponse

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Every request/response line goes through print() -> the rotating log
    file (see logging_config.py), same as the rest of the app's error prints."""
    start = time.time()
    response = await call_next(request)
    duration_ms = int((time.time() - start) * 1000)
    print(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"},
    )


# CORSMiddleware must be added last so it wraps all responses (including exception handlers & log_requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173","http://localhost:8001","http://127.0.0.1:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(connections.router)
app.include_router(sql_examples.router)
app.include_router(master_data.router)
app.include_router(reports.router)
app.include_router(report_schedules.router)
app.include_router(chat.router)
app.include_router(chat_sessions.router)
app.include_router(training.router)
app.include_router(settings.router)
app.include_router(usage.router)


@app.on_event("startup")
async def _startup() -> None:
    """Brings the metadata MariaDB database's schema up to date on boot, so
    `uvicorn app.main:app` alone is enough in dev — no separate migration
    step to remember (see app/database.py / migrations/), then starts the
    schedule poller (app/scheduler.py) — its first poll immediately catches
    up on any report schedules that were due while the backend was down,
    running them one at a time, before settling into its normal interval."""
    try:
        await asyncio.to_thread(run_migrations)
    except Exception as e:
        print(f"Error migrating metadata database -- {e}")
        logger.exception("Error migrating metadata database")
        raise RuntimeError(
            "Could not reach the metadata database (connections/reports/chat/settings "
            "storage). By default QuickInsights expects the bundled Docker MariaDB — "
            "run:\n"
            "    docker compose --profile docker-db up -d\n"
            "or use ./setup_metadata_db.sh to pick standalone Docker vs. an existing "
            "Frappe/MariaDB server instead.\n"
            f"Underlying error: {e}"
        ) from e
    finally:
        # run_migrations() -> Alembic's migrations/env.py calls
        # logging.config.fileConfig(alembic.ini) on every run, which resets
        # the ROOT logger's handlers/level regardless of outcome — put ours
        # back so logger.info()/.warning() calls anywhere in the app keep
        # reaching the log file, not just print()-based ones. See
        # reassert_root_logging()'s docstring for the full explanation.
        reassert_root_logging()

    start_scheduler()


@app.get("/")
def root():
    return {"status": "ok", "service": "quickinsights-api", "docs": "/docs"}
