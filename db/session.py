"""
Database connection.

The database location comes from the DATABASE_URL setting in the .env file:
  - Local development : sqlite:///data/app.db           (default)
  - Deployment        : postgresql://user:password@host:5432/dbname?sslmode=require
                        (from Neon / Supabase; on Streamlit Cloud put it in the app's Secrets)

Switching from SQLite to PostgreSQL only needs a different DATABASE_URL;
the models and migrations stay the same.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_SQLITE = f"sqlite:///{(ROOT / 'data' / 'app.db').as_posix()}"


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip() or DEFAULT_SQLITE
    # Hosting providers give "postgres://" or "postgresql://"; SQLAlchemy needs the driver name (psycopg 3)
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
    # Relative SQLite paths are resolved from the project folder, not the terminal's folder
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and ":" not in url[10:12]:
        url = f"sqlite:///{(ROOT / url[10:]).as_posix()}"
    if url.startswith("sqlite"):
        (ROOT / "data").mkdir(exist_ok=True)
    return url


DATABASE_URL = get_database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    # SQLite ignores foreign keys unless this is switched on for every connection
    if IS_SQLITE:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session() -> Session:
    """Use as:  with get_session() as s: ...   (commits on success, rolls back on error)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def describe_database() -> str:
    """Safe description for logs (never prints a password)."""
    if IS_SQLITE:
        return f"SQLite file: {DATABASE_URL.replace('sqlite:///', '')}"
    return f"{engine.url.get_backend_name()} database '{engine.url.database}' on {engine.url.host}"
