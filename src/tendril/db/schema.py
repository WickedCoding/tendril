from __future__ import annotations

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tendril.db.models import Base, SyncState

SCHEMA_VERSION = 1


def init_schema(engine: Engine) -> None:
    """Create all tables and ensure the singleton SyncState row exists."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        row = session.get(SyncState, 1)
        if row is None:
            session.add(SyncState(id=1, schema_version=SCHEMA_VERSION))
            session.commit()
        elif row.schema_version != SCHEMA_VERSION:
            raise RuntimeError(
                f"Local DB is schema version {row.schema_version}, "
                f"but this build expects {SCHEMA_VERSION}. Migrations not implemented yet."
            )


def get_sync_state(session: Session) -> SyncState:
    row = session.get(SyncState, 1)
    if row is None:
        raise RuntimeError("SyncState singleton missing — did init_schema() run?")
    return row
