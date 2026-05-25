from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .. import db
from ..providers.base import MarketDataProvider

_MAX_LOOKBACK_DAYS: dict[str, int] = {
    "1m":  7,
    "5m":  60,
    "15m": 60,
    "30m": 60,
    "1h":  720,
    "4h":  720,
    "1d":  36500,
}


class DataService:
    def __init__(self, provider: MarketDataProvider, db_buffer_days: int = 3):
        self.provider = provider
        self.db_buffer_days = db_buffer_days

    def get_close_series(
        self, ticker: str, years: int, interval: str = "1d"
    ) -> tuple[pd.Series, dict]:
        end = pd.Timestamp.now(tz="UTC").normalize().to_pydatetime()

        max_days = _MAX_LOOKBACK_DAYS.get(interval, 730)
        requested_days = years * 365
        actual_days = min(requested_days, max_days)

        with db.connect() as conn:
            db.ensure_schema(conn)
            last_ts = db.get_last_ts(conn, ticker=ticker, provider=self.provider.name(), interval=interval)

            if last_ts is None:
                start = end - timedelta(days=actual_days)
            else:
                start = last_ts - timedelta(days=self.db_buffer_days)

            bars = self.provider.fetch_history(ticker, start=start, end=end, interval=interval)
            rows_upserted = db.upsert_price_bars(conn, provider=self.provider.name(), bars=bars)
            close = db.load_close_series(conn, ticker=ticker, provider=self.provider.name(), interval=interval)

        meta = {
            "provider": self.provider.name(),
            "interval": interval,
            "last_ts_before": last_ts.isoformat() if last_ts else None,
            "fetch_start": start.isoformat(),
            "fetch_end": end.isoformat(),
            "rows_fetched": len(bars),
            "rows_upserted": rows_upserted,
        }
        return close, meta
