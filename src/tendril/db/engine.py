from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from tendril.config import data_dir


def db_path() -> Path:
    return data_dir() / "tendril.db"


def build_engine(path: Path | None = None) -> Engine:
    if path is None:
        path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def _apply_pragmas(dbapi_connection, _connection_record) -> None:
        # WAL keeps readers and a single writer from blocking each other,
        # which matters once the TUI does a background sync while the UI reads.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
