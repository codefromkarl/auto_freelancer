import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_SERVICE = REPO_ROOT / "python_service"
sys.path.insert(0, str(PYTHON_SERVICE))

from utils.currency_converter import CurrencyConverter


def test_get_rate_sync_fallback_on_missing(monkeypatch):
    converter = CurrencyConverter(cache_file=":memory:")
    converter.rates = {"USD": 1.0}
    converter.last_updated = 0.0

    def _no_update(*_args, **_kwargs):
        return None

    monkeypatch.setattr(converter, "update_rates_sync", _no_update)
    assert converter.get_rate_sync("INR") == 0.012
    assert converter.get_rate_sync("XXX") is None


async def _get_rate_async(converter, code):
    return await converter.get_rate(code)


def test_get_rate_async_fallback_on_missing(monkeypatch):
    converter = CurrencyConverter(cache_file=":memory:")
    converter.rates = {"USD": 1.0}
    converter.last_updated = 0.0

    async def _no_update(*_args, **_kwargs):
        return None

    monkeypatch.setattr(converter, "update_rates", _no_update)
    assert asyncio.run(_get_rate_async(converter, "VND")) == 0.000041
    assert asyncio.run(_get_rate_async(converter, "ZZZ")) is None
