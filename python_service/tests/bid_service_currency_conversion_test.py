import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.connection import Base
from database.models import Project
from services import bid_service


@pytest.mark.parametrize("amount,currency,expected", [
    (585.0, "USD", 39000.0), (40000.0, "INR", 40000.0),
    (585.0, "INR", 585.0), (585.0, None, 585.0),
])
def test_bid_currency_is_explicit(monkeypatch, amount, currency, expected):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = SimpleNamespace(user_id=999,
        get_project=AsyncMock(return_value={"status": "open"}),
        create_bid=AsyncMock(return_value={"id": 112233, "bidder_id": 999}))
    monkeypatch.setattr(bid_service, "get_freelancer_client", lambda: client)
    monkeypatch.setattr(bid_service, "get_currency_converter", lambda: SimpleNamespace(get_rate_sync=lambda _: 0.015))
    monkeypatch.setattr(bid_service, "check_content_risk", lambda *_: (True, "ok"))
    with Session(engine) as db:
        db.add(Project(freelancer_id=123, title="INR Project", currency_code="INR", suggested_bid=585))
        db.commit()
        result = asyncio.run(bid_service.create_bid(db, 123, amount, 7, "Final proposal", amount_currency=currency))
        assert result["amount"] == expected
        assert client.create_bid.call_args.kwargs["amount"] == expected
    engine.dispose()


def test_missing_exchange_rate_blocks_native_amount(monkeypatch):
    monkeypatch.setattr(bid_service, "get_currency_converter", lambda: SimpleNamespace(get_rate_sync=lambda _: None))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = SimpleNamespace(create_bid=AsyncMock())
    monkeypatch.setattr(bid_service, "get_freelancer_client", lambda: client)
    with Session(engine) as db:
        db.add(Project(freelancer_id=123, title="Unknown Currency", currency_code="XXX"))
        db.commit()
        with pytest.raises(ValueError, match="missing exchange rate"):
            asyncio.run(bid_service.create_bid(db, 123, 100, 7, "Final proposal"))
    client.create_bid.assert_not_called()
    engine.dispose()
