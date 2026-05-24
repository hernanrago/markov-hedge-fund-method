from __future__ import annotations

import os

from .base import MarketDataProvider
from .yahoo import YahooProvider


def get_provider() -> MarketDataProvider:
    provider = os.environ.get("MARKET_DATA_PROVIDER", "yahoo").strip().lower()
    if provider == "yahoo":
        return YahooProvider()
    raise ValueError(f"Unsupported MARKET_DATA_PROVIDER='{provider}'")
