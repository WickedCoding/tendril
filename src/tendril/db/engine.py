from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from tendril.config import data_dir


def db_path() -> Path:
    return data_dir() / "tendril.db"


def build_engine(path: Path | None = None) -> Engine:
    if path is None:
        path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
