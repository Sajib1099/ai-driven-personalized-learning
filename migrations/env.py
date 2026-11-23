"""Alembic migration environment — uses DATABASE_URL from .env (via db.session)."""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # make "db" importable

from db.models import Base  # noqa: E402
from db.session import DATABASE_URL, IS_SQLITE, engine  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=IS_SQLITE, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        # render_as_batch lets Alembic alter tables on SQLite (which has limited ALTER TABLE)
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=IS_SQLITE, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
