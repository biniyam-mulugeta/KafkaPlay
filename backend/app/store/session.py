"""SQLite engine setup.

WAL mode matters here: the background offset sampler writes continuously while
API requests read. Without WAL those readers would block behind the writer.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine

# Importing the models registers them on SQLModel.metadata before create_all.
from app.store import models as _models  # noqa: F401


def _sqlite_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw = database_url[len(prefix) :]
    if raw == ":memory:" or raw.startswith(":memory:"):
        return None
    return Path(raw)


def create_db_engine(database_url: str, echo: bool = False) -> Engine:
    is_sqlite = database_url.startswith("sqlite")

    path = _sqlite_path(database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)

    connect_args: dict[str, Any] = {}
    if is_sqlite:
        # FastAPI serves requests from a thread pool; SQLite's default
        # same-thread check would reject those connections.
        connect_args["check_same_thread"] = False

    engine = create_engine(database_url, echo=echo, connect_args=connect_args)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            # Wait rather than immediately raising "database is locked".
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on failure."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
