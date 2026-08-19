"""SQLAlchemy engine/session for QuickInsights' own metadata database
(connections, reports, schedules, SQL examples, training state) — separate
from the user databases the app connects to via app/db.py."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import METADATA_DATABASE_URL

engine = create_engine(METADATA_DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def run_migrations() -> None:
    """Bring the metadata database schema up to date via Alembic. Called on
    backend startup so `uvicorn app.main:app` alone is enough in dev — no
    separate migration step to remember."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    cfg.set_main_option("sqlalchemy.url", METADATA_DATABASE_URL)
    command.upgrade(cfg, "head")
