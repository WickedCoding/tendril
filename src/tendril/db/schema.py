from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def init_schema(engine: Engine) -> None:
    """Bring the DB up to head by running Alembic migrations.

    Safe to call on an empty file (applies every migration) and on an already
    up-to-date DB (no-op). Passes the engine's URL to env.py via TENDRIL_DB_URL
    so callers only pass an Engine and never touch alembic.ini.
    """
    cfg = _alembic_config()
    prev = os.environ.get("TENDRIL_DB_URL")
    os.environ["TENDRIL_DB_URL"] = str(engine.url)
    try:
        command.upgrade(cfg, "head")
    finally:
        if prev is None:
            os.environ.pop("TENDRIL_DB_URL", None)
        else:
            os.environ["TENDRIL_DB_URL"] = prev
