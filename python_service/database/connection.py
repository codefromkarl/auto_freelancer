"""
Database connection and session management.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.pool import NullPool
from contextlib import contextmanager
from fastapi import Request, HTTPException, status
import os


# Base class for SQLAlchemy models
class Base(DeclarativeBase):
    pass


# Import settings
from config import settings

# Create database engine
DATABASE_URL = f"sqlite:///{settings.DATABASE_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_wal_mode(dbapi_connection, connection_record):
    """Enable WAL journal mode for better concurrent read/write performance."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_add_columns(eng):
    """Add new columns to existing tables (idempotent)."""
    from sqlalchemy import text, inspect
    insp = inspect(eng)
    if "projects" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("projects")}
        if "competitor_bids_fetched_at" not in cols:
            with eng.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE projects ADD COLUMN competitor_bids_fetched_at DATETIME"
                ))


def init_db():
    """Initialize database and create all tables."""
    import os
    # Import models here to register them with Base.metadata
    from . import models

    db_path = settings.DATABASE_PATH
    db_dir = os.path.dirname(db_path)

    # Ensure data directory exists
    os.makedirs(db_dir, exist_ok=True)

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Lightweight migrations for new columns on existing tables
    _migrate_add_columns(engine)


@contextmanager
def get_db_session():
    """Context manager for database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def get_db():
    """Dependency for FastAPI to get database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


async def verify_api_key(request: Request):
    """Verify API key from request header.

    Supports BYPASS_AUTH=true environment variable for local testing only.
    """
    # Allow bypassing auth in test/dev environments via explicit env var
    if os.environ.get("BYPASS_AUTH", "").lower() == "true":
        return "bypass-auth"

    api_key = request.headers.get("X-API-Key")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key"
        )

    if api_key != settings.PYTHON_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )

    return api_key
