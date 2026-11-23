"""
Start-up preparation for hosted deployments (e.g. Streamlit Community Cloud), where
no terminal commands can be run:

  1. apply database migrations (alembic upgrade head)
  2. if SEED_DEMO_ON_EMPTY is "true" and the database has no users yet, add the demo data

Locally you can keep running the commands by hand; running this as well is harmless.
"""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select

ROOT = Path(__file__).resolve().parents[1]


def migrate() -> None:
    cfg = Config()                     # no ini file: keeps the app's own logging configuration
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


def seed_if_empty() -> bool:
    if os.getenv("SEED_DEMO_ON_EMPTY", "false").strip().lower() not in ("1", "true", "yes"):
        return False
    from db.models import User
    from db.session import get_session
    with get_session() as s:
        if s.scalar(select(func.count()).select_from(User)) > 0:
            return False
    from scripts import seed_demo
    seed_demo.seed()
    return True


def prepare_database() -> dict:
    migrate()
    from db.session import engine
    seeded = seed_if_empty()
    return {"tables": len(inspect(engine).get_table_names()), "seeded": seeded}
