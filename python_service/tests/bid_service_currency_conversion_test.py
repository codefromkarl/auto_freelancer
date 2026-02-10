import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import bid_service


class _FakeBidStatusField:
    def in_(self, _values):
        return True


class _FakeBidModel:
    status = _FakeBidStatusField()

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeProject:
    def __init__(self):
        self.id = 1
        self.freelancer_id = 40136605
        self.title = "INR Project"
        self.description = "desc"
        self.preview_description = "preview"
        self.status = "active"
        self.currency_code = "INR"
        self.budget_minimum = 37500
        self.budget_maximum = None
        self.suggested_bid = 585.0  # USD suggested by AI
        self.ai_proposal_draft = None


class _FakeQuery:
    def __init__(self, item):
        self._item = item

    def filter_by(self, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._item


class _FakeDB:
    def __init__(self, project):
        self.project = project
        self.added = []

    def query(self, model):
        if model is bid_service.Project:
            return _FakeQuery(self.project)
        return _FakeQuery(None)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


class _FakeClient:
    user_id = 999

    def __init__(self):
        self.sent_amount = None

    async def create_bid(self, project_id, amount, period, description):
        self.sent_amount = amount
        return {
            "result": {
                "id": 112233,
                "bidder_id": 999,
            }
        }


class _FakeConverter:
    def get_rate_sync(self, currency_code):
        assert currency_code == "INR"
        return 0.015  # 1 INR = 0.015 USD


def test_create_bid_converts_suggested_usd_amount_to_project_currency(monkeypatch):
    fake_project = _FakeProject()
    fake_db = _FakeDB(fake_project)
    fake_client = _FakeClient()

    monkeypatch.setattr(bid_service, "Bid", _FakeBidModel)
    monkeypatch.setattr(bid_service, "get_freelancer_client", lambda: fake_client)
    monkeypatch.setattr(bid_service, "get_currency_converter", lambda: _FakeConverter(), raising=False)

    result = asyncio.run(
        bid_service.create_bid(
            db=fake_db,
            project_id=fake_project.freelancer_id,
            amount=585.0,
            period=7,
            description="x" * 120,
            skip_content_check=True,
            validate_remote_status=False,
        )
    )

    assert fake_client.sent_amount == 39000.0
    assert result["amount"] == 39000.0


def test_create_bid_keeps_non_suggested_amount_unchanged(monkeypatch):
    fake_project = _FakeProject()
    fake_db = _FakeDB(fake_project)
    fake_client = _FakeClient()

    monkeypatch.setattr(bid_service, "Bid", _FakeBidModel)
    monkeypatch.setattr(bid_service, "get_freelancer_client", lambda: fake_client)
    monkeypatch.setattr(bid_service, "get_currency_converter", lambda: _FakeConverter(), raising=False)

    result = asyncio.run(
        bid_service.create_bid(
            db=fake_db,
            project_id=fake_project.freelancer_id,
            amount=40000.0,
            period=7,
            description="x" * 120,
            skip_content_check=True,
            validate_remote_status=False,
        )
    )

    assert fake_client.sent_amount == 40000.0
    assert result["amount"] == 40000.0
