from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .. import db
from ..providers.base import MarketDataProvider


class DataService:
    def __init__(self, provider: MarketDataProvider, db_buffer_days: int = 3):
        self.provider = provider
        self.db_buffer_days = db_buffer_days

    def get_close_series(self, ticker: str, years: int) -> tuple[pd.Series, dict]:
        end = pd.Timestamp.now(tz="UTC").normalize().date()

        with db.connect() as conn:
            db.ensure_schema(conn)
            last_date = db.get_last_date(conn, ticker=ticker, provider=self.provider.name())

            if last_date is None:
                start = (pd.Timestamp(end) - pd.DateOffset(years=years)).date()
            else:
                start = last_date - timedelta(days=self.db_buffer_days)

            bars = self.provider.fetch_history(ticker, start=start, end=end)
            rows_upserted = db.upsert_price_bars(conn, provider=self.provider.name(), bars=bars)
            close = db.load_close_series(conn, ticker=ticker, provider=self.provider.name())

        meta = {
            "provider": self.provider.name(),
            "last_date_before": last_date.isoformat() if last_date else None,
            "fetch_start": start.isoformat(),
            "fetch_end": end.isoformat(),
            "rows_fetched": len(bars),
            "rows_upserted": rows_upserted,
        }
        return close, meta
