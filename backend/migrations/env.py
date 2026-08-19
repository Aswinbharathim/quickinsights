from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base
from app.config import METADATA_DATABASE_URL
import app.db_models  # noqa: F401 — registers all tables on Base.metadata

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False — this env.py runs on every migration,
    # including from run_migrations() at backend startup (app/database.py),
    # not just the standalone `alembic` CLI. fileConfig's default
    # (disable_existing_loggers=True) reconfigures the ROOT logger per
    # alembic.ini's own [logger_root] (a bare stderr StreamHandler at
    # WARNING) and disables every other already-registered logger not
    # listed in alembic.ini's [loggers] section — which is every logger our
    # app itself set up in logging_config.py, module-level `logger =
    # logging.getLogger(__name__)` calls included. That silently broke ALL
    # of the app's own file logging (both the print()-redirect trick and
    # direct logger.error()/.exception() calls anywhere in the codebase) the
    # moment the very first migration ran after startup.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", METADATA_DATABASE_URL)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=METADATA_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
