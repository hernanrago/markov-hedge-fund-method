from __future__ import annotations

from datetime import date

import pandas as pd
import yfinance as yf

from .base import PriceBar


class YahooProvider:
    def name(self) -> str:
        return "yahoo"

    def fetch_history(self, symbol: str, start: date, end: date) -> list[PriceBar]:
        df = yf.download(
            symbol,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return []

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        bars: list[PriceBar] = []
        for idx, row in df.iterrows():
            bars.append(
                PriceBar(
                    ticker=symbol,
                    provider_symbol=symbol,
                    date=idx.date(),
                    open=_maybe_float(row.get("Open")),
                    high=_maybe_float(row.get("High")),
                    low=_maybe_float(row.get("Low")),
                    close=_maybe_float(row.get("Close")),
                    volume=_maybe_float(row.get("Volume")),
                )
            )
        return bars


def _maybe_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
