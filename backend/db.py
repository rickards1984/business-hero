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

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    parsed = urlparse(DATABASE_URL)
    logger.info(f"Connecting to PostgreSQL database at host: {parsed.hostname}")
    
    try:
        engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
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
