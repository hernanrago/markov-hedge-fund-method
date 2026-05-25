from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PriceBar:
    """Represents a single OHLCV price bar for a given ticker and interval."""
    ticker: str
    provider_symbol: str
    interval: str          # e.g. '1d', '1h', '4h', '15m', '5m'
    ts: datetime           # UTC
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class MarketDataProvider(Protocol):
    def name(self) -> str:
        ...

    def fetch_history(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> list[PriceBar]:
        ...
