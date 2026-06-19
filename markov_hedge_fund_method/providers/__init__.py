from __future__ import annotations

import os

from .base import MarketDataProvider
from .bingx import BingXProvider
from .yahoo import YahooProvider


def get_provider() -> MarketDataProvider:
    provider = os.environ.get("MARKET_DATA_PROVIDER", "yahoo").strip().lower()
    if provider == "yahoo":
        return YahooProvider()
    if provider == "bingx":
        return BingXProvider()
    raise ValueError(f"Unsupported MARKET_DATA_PROVIDER='{provider}'")
