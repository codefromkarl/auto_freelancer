"""
Database connection and session management.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
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
    poolclass=StaticPool,
    echo=False,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
