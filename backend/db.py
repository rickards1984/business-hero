"""Database configuration and session management."""

import os
import sys
import logging
from urllib.parse import urlparse
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_DATABASE_URL")
DATABASE_URL = SUPABASE_URL or os.getenv("DATABASE_URL")
SQLITE_DATABASE_URL = os.getenv("SQLITE_DATABASE_URL", "sqlite:///./data.db")


def normalise_database_url(url: str) -> str:
    """Name the PostgreSQL driver explicitly.

    `postgresql://` means "the dialect's default driver", and that default
    changed: SQLAlchemy 2.1 picks psycopg (v3), which is not installed, where
    2.0 picked psycopg2, which is. On 8 Oct 2026 an unpinned deploy resolved
    to 2.1 and every boot failed with "No module named 'psycopg'". Naming
    psycopg2 makes a future upgrade fail loudly in tests, not in production.
    An explicitly chosen driver (postgresql+anything://) is left alone.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def _pool_setting(name: str, default: int, highest: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError:
        return default
    return value if 1 <= value <= highest else default


# The most connections one process may hold. Supabase allows about 60 on the
# Micro compute (session mode and direct alike), and Supabase's own services
# use some. Production runs ONE uvicorn process (Procfile, railway.json): a
# second process or replica doubles the total, so halve this before adding one.
POOL_BUDGET = 30


def pool_options() -> dict:
    """STAB-1: the old default, 5 + 10 with a 30-second wait, ran out on 18 Nov
    2026 and froze the app. 10 + 10 is 20 connections, inside POOL_BUDGET; a
    wait of 10 seconds fails one request quickly instead of queueing all of
    them. DB_POOL_SIZE, DB_MAX_OVERFLOW and DB_POOL_TIMEOUT tune it without a
    release; a value that isn't a sensible number, or a pair over the budget,
    is ignored in favour of the defaults (Codex code review 1, finding 3)."""
    size = _pool_setting("DB_POOL_SIZE", 10, POOL_BUDGET)
    overflow = _pool_setting("DB_MAX_OVERFLOW", 10, POOL_BUDGET)
    if size + overflow > POOL_BUDGET:
        size, overflow = 10, 10
    return {
        "pool_size": size,
        "max_overflow": overflow,
        "pool_timeout": _pool_setting("DB_POOL_TIMEOUT", 10, 60),
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }


if DATABASE_URL:
    DATABASE_URL = normalise_database_url(DATABASE_URL)
    
    parsed = urlparse(DATABASE_URL)
    logger.info(f"Connecting to PostgreSQL database at host: {parsed.hostname}")
    
    try:
        engine = create_engine(DATABASE_URL, echo=False, **pool_options())
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(f"Successfully connected to PostgreSQL at {parsed.hostname}")
    except Exception as e:
        logger.error(f"FATAL: Failed to connect to PostgreSQL at {parsed.hostname}: {e}")
        sys.exit(1)
else:
    logger.info("No DATABASE_URL found - using SQLite for local development")
    connect_args = {"check_same_thread": False}
    engine = create_engine(SQLITE_DATABASE_URL, echo=False, connect_args=connect_args)


def init_db():
    """Initialize the database, creating all tables if they don't exist."""
    from models import Business, Task, CallEvent  # noqa: F401
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency for getting a database session."""
    with Session(engine) as session:
        yield session


@contextmanager
def get_session_context():
    """Context manager for database session."""
    with Session(engine) as session:
        yield session


_safety_logger = logging.getLogger("db.transactional")


@contextmanager
def get_session_transactional():
    """
    Context manager for a database session with explicit commit/rollback.

    On clean exit: commits the transaction.
    On exception: rolls back, logs the function name and exception, re-raises.

    Use this for any code path that performs writes. Reads can use
    get_session_context() — auto-commit is harmless for read-only queries
    but explicit transactional intent is preferred for writes.
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception as rollback_exc:
            _safety_logger.error(
                "Rollback itself failed: %s (original: %s)",
                rollback_exc, exc
            )
        _safety_logger.warning(
            "Transaction rolled back: %s",
            exc, exc_info=True
        )
        raise
    finally:
        session.close()
