"""File logging setup — daily-rotating log file (7 days retained), capturing
BOTH of this project's two logging conventions into the same file:

1. Every existing `print(f"Error ... -- {e}")` call (routers/rag.py/etc.) and
   the request-logging middleware in main.py — captured by transparently
   replacing `sys.stdout`/`sys.stderr` with a small proxy that still writes
   to the real terminal and additionally forwards each line into a
   `TimedRotatingFileHandler`-backed logger. No print() call site needs to
   change for this to work, since `print()` resolves `sys.stdout` at call
   time, not at import time.
2. Every `logger.error(...)`/`logger.exception(...)` call made via the
   standard `logging.getLogger(__name__)` pattern anywhere in the app —
   captured by attaching the SAME handler to the root logger, so any
   module logger (which propagates up to root by default) lands in the
   identical file, with real levels/tracebacks this time.

Call `setup_logging()` once, as early as possible in `main.py`, before
anything else has a chance to print or log.
"""
import logging
import logging.handlers
import os
import sys

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

ROTATE_WHEN = "midnight"   # new file every day
ROTATE_INTERVAL = 1
RETENTION_DAYS = 7         # older rotated files are auto-deleted


class _StreamToLogger:
    """Proxies a stream (stdout/stderr): keeps writing to the real terminal
    exactly as before, and additionally forwards each complete line to the
    given logger so it lands in the rotating file too."""

    def __init__(self, logger: logging.Logger, level: int, original_stream):
        self._logger = logger
        self._level = level
        self._original_stream = original_stream
        self._buffer = ""

    def write(self, message: str) -> int:
        self._original_stream.write(message)
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line)
        return len(message)

    def flush(self) -> None:
        self._original_stream.flush()
        if self._buffer.strip():
            self._logger.log(self._level, self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        return False


_configured = False
_handler: logging.Handler | None = None


def setup_logging() -> logging.Logger:
    """Idempotent — safe to call more than once (e.g. under `--reload`, or
    via reassert_root_logging() below)."""
    global _configured, _handler
    logger = logging.getLogger("quickinsights")
    if _configured:
        return logger

    os.makedirs(LOG_DIR, exist_ok=True)

    handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOG_FILE,
        when=ROTATE_WHEN,
        interval=ROTATE_INTERVAL,
        backupCount=RETENTION_DAYS,
        encoding="utf-8",
    )
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _handler = handler

    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    # Also attach to the root logger, so any module's standard
    # `logging.getLogger(__name__)` -> `logger.error(...)`/`.exception(...)`
    # calls propagate up and land in this same file, alongside the print()
    # mirror above — both conventions, one file.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    sys.stdout = _StreamToLogger(logger, logging.INFO, sys.__stdout__)
    sys.stderr = _StreamToLogger(logger, logging.ERROR, sys.__stderr__)

    _configured = True
    return logger


def reassert_root_logging() -> None:
    """Re-attaches our handler to the root logger and resets its level to
    INFO. Call this after anything that might reconfigure logging out from
    under us — specifically, `run_migrations()` (app/database.py) runs
    Alembic's `migrations/env.py`, which calls `logging.config.fileConfig()`
    on every single migration run, not just once at import time. fileConfig
    always reapplies alembic.ini's own `[logger_root]` section (a bare
    stderr handler at WARNING) to the ROOT logger specifically, regardless
    of `disable_existing_loggers` — that flag only protects OTHER, unlisted
    loggers (which is why our own module loggers survive fine without this,
    but root itself doesn't). Without this call, every module-level
    `logger.info()`/`.warning()` call that relies on inheriting root's level
    would go silent the moment the very first migration ran after startup,
    even though print()-based logging (routed through the "quickinsights"
    logger's own directly-attached handler, unaffected by root) keeps
    working regardless."""
    if not _configured or _handler is None:
        return
    root_logger = logging.getLogger()
    # Replace root's handlers outright, not just ensure ours is present —
    # fileConfig also leaves its own stderr-bound console handler sitting on
    # root. That handler's stream is our sys.stderr proxy (captured by
    # reference when fileConfig evaluated alembic.ini's handler args), so
    # anything reaching it loops back through the "quickinsights" logger's
    # own handler a second time, duplicating (and mislabeling as ERROR) any
    # message that also reaches root directly through this handler.
    for h in root_logger.handlers[:]:
        if h is not _handler:
            root_logger.removeHandler(h)
    if _handler not in root_logger.handlers:
        root_logger.addHandler(_handler)
    root_logger.setLevel(logging.INFO)
