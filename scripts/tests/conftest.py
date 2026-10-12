from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import common
from database.connection import Base


@pytest.fixture
def workflow_db(monkeypatch):
    """Cycle tests now persist observations in the same isolated database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    @contextmanager
    def scope():
        with Session(engine) as db:
            yield db
            db.commit()
    monkeypatch.setattr(common, "get_db_context", scope)
    yield scope
    engine.dispose()
