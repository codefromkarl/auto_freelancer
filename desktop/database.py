"""Local schema and durable jobs; never opens the personal runtime database."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LocalBase(DeclarativeBase):
    pass


class Job(LocalBase):
    __tablename__ = "local_jobs"
    id = Column(String(32), primary_key=True)
    project_id = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)
    state = Column(String(20), nullable=False, index=True)
    config_revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=now)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    result = Column(Text)
    error = Column(Text)


class Database:
    def __init__(self, directory):
        self.path = Path(directory) / "projects.db"
        self.engine = create_engine(
            URL.create("sqlite", database=str(self.path)),
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(self.engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")

        from database.connection import Base
        import database.models  # noqa: F401 - register the existing engine tables

        Base.metadata.create_all(self.engine)
        LocalBase.metadata.create_all(self.engine)
        with self.session() as db:
            for job in db.query(Job).filter(Job.state.in_(["queued", "running"])).all():
                job.state = "interrupted"
                job.finished_at = now()
                job.error = (
                    "Interrupted by a previous shutdown. Review before retrying."
                )

    @contextmanager
    def session(self):
        with Session(self.engine, autoflush=False, expire_on_commit=False) as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def backup(self, destination):
        import sqlite3

        with (
            closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(destination)) as dst,
            dst,
        ):
            src.backup(dst)
