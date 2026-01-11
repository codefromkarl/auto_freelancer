"""
Currency converter utility using Frankfurter API.
"""
import json
import logging
import os
import time
from typing import Dict, Optional
import httpx

logger = logging.getLogger(__name__)

class CurrencyConverter:
    """
    Handles currency conversion rates with 24-hour caching.
    Rates are stored as 'value of 1 unit of currency in USD'.
    Example: if 1 USD = 83 INR, then INR rate is 1/83 = 0.012048.
    """
    
    API_URL = "https://api.frankfurter.app/latest"
    CACHE_FILE = "data/currency_rates.json"
    CACHE_TTL = 24 * 3600  # 24 hours
    FALLBACK_RATES = {
        "INR": 0.012,
        "IDR": 0.000064,
        "VND": 0.000041,
    }
    
    def __init__(self, cache_file: Optional[str] = None):
        self.cache_file = cache_file or self.CACHE_FILE
        self.rates: Dict[str, float] = {"USD": 1.0}
        self.last_updated = 0.0
        self._ensure_data_dir()
        self.load_cache()

    def _ensure_data_dir(self):
        """Ensure the directory for the cache file exists."""
        data_dir = os.path.dirname(self.cache_file)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)

    def load_cache(self):
        """Load rates from the cache file."""
        if not os.path.exists(self.cache_file):
            return

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.rates = data.get("rates", {"USD": 1.0})
                self.last_updated = data.get("last_updated", 0.0)
                logger.info(f"Loaded {len(self.rates)} currency rates from cache")
        except Exception as e:
            logger.error(f"Failed to load currency cache: {e}")

    def save_cache(self):
        """Save current rates to the cache file."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "rates": self.rates,
                    "last_updated": self.last_updated
                }, f, indent=2)
            logger.info(f"Saved {len(self.rates)} currency rates to cache")
        except Exception as e:
            logger.error(f"Failed to save currency cache: {e}")

    def is_cache_valid(self) -> bool:
        """Check if the cache is still valid (less than TTL)."""
        return (time.time() - self.last_updated) < self.CACHE_TTL

    def update_rates_sync(self, target_currency: Optional[str] = None):
        """Fetch latest rates from API synchronously."""
        params = {"from": "USD"}
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(self.API_URL, params=params)
                response.raise_for_status()
                data = response.json()
                
                new_rates = {"USD": 1.0}
                for code, rate in data.get("rates", {}).items():
                    if rate > 0:
                        new_rates[code] = 1.0 / rate
                
                self.rates = new_rates
                self.last_updated = time.time()
                self.save_cache()
                logger.info("Successfully updated currency rates from API (sync)")
        except Exception as e:
            logger.error(f"Failed to update currency rates (sync): {e}")

    async def update_rates(self, target_currency: Optional[str] = None):
        """
        Fetch latest rates from API.
        If target_currency is provided, ensure it's included.
        """
        params = {"from": "USD"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.API_URL, params=params)
                response.raise_for_status()
                data = response.json()
                
                new_rates = {"USD": 1.0}
                # Frankfurter returns rates as: 1 USD = X Currency
                # We want: 1 Currency = Y USD -> Y = 1/X
                for code, rate in data.get("rates", {}).items():
                    if rate > 0:
                        new_rates[code] = 1.0 / rate
                
                self.rates = new_rates
                self.last_updated = time.time()
                self.save_cache()
                logger.info("Successfully updated currency rates from API")
        except Exception as e:
            logger.error(f"Failed to update currency rates: {e}")

    def get_rate_sync(self, currency_code: str) -> Optional[float]:
        """
        Get the exchange rate for a currency (to USD) synchronously.
        """
        currency_code = currency_code.upper()
        if currency_code == "USD":
            return 1.0

        if not self.is_cache_valid() or currency_code not in self.rates:
            logger.info(f"Rate for {currency_code} missing or cache expired, updating (sync)...")
            self.update_rates_sync(currency_code)

        rate = self.rates.get(currency_code)
        if rate is None:
            rate = self.FALLBACK_RATES.get(currency_code)
        if rate is None:
            logger.warning(f"Exchange rate for {currency_code} not found, no fallback available")
        return rate

    async def get_rate(self, currency_code: str) -> Optional[float]:
        """
        Get the exchange rate for a currency (to USD).
        Fetches from API if cache is expired or currency is missing.
        """
        currency_code = currency_code.upper()
        
        if currency_code == "USD":
            return 1.0

        # If cache expired or currency missing, try to update
        if not self.is_cache_valid() or currency_code not in self.rates:
            logger.info(f"Rate for {currency_code} missing or cache expired, updating...")
            await self.update_rates(currency_code)

        rate = self.rates.get(currency_code)
        if rate is None:
            rate = self.FALLBACK_RATES.get(currency_code)
        if rate is None:
            # If still missing (maybe not supported by API), return None for callers to handle
            logger.warning(f"Exchange rate for {currency_code} not found, no fallback available")
        return rate

# Singleton instance
_converter: Optional[CurrencyConverter] = None

def get_currency_converter() -> CurrencyConverter:
    global _converter
    if _converter is None:
        _converter = CurrencyConverter()
    return _converter
