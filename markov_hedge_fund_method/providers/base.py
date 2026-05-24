from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PriceBar:
    ticker: str
    provider_symbol: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class MarketDataProvider(Protocol):
    def name(self) -> str:
        ...

    def fetch_history(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        ...
