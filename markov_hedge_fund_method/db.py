from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator

import pandas as pd
import psycopg

from .providers.base import PriceBar


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS price_history (
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    interval TEXT NOT NULL DEFAULT '1d',
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_symbol, interval, ts)
);

CREATE INDEX IF NOT EXISTS idx_price_history_ticker_ts
    ON price_history (ticker, interval, ts DESC);
"""


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for DB mode")
    with psycopg.connect(database_url) as conn:
        yield conn


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        # Check if old schema (has 'date' column)
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'price_history' AND column_name = 'date'
              AND table_schema = current_schema()
            """
        )
        has_old_schema = cur.fetchone() is not None

        if has_old_schema:
            # Migrate: date DATE → ts TIMESTAMPTZ + add interval TEXT
            cur.execute("ALTER TABLE price_history ADD COLUMN IF NOT EXISTS interval TEXT")
            cur.execute("UPDATE price_history SET interval = '1d' WHERE interval IS NULL")
            cur.execute("ALTER TABLE price_history ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ")
            cur.execute("UPDATE price_history SET ts = (date::timestamp AT TIME ZONE 'UTC') WHERE ts IS NULL")
            cur.execute("ALTER TABLE price_history DROP CONSTRAINT price_history_pkey")
            cur.execute("ALTER TABLE price_history ALTER COLUMN interval SET NOT NULL")
            cur.execute("ALTER TABLE price_history ALTER COLUMN ts SET NOT NULL")
            cur.execute(
                "ALTER TABLE price_history ADD PRIMARY KEY (provider, provider_symbol, interval, ts)"
            )
            cur.execute("ALTER TABLE price_history DROP COLUMN date")
            cur.execute("DROP INDEX IF EXISTS idx_price_history_ticker_date")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_price_history_ticker_ts
                    ON price_history (ticker, interval, ts DESC)
                """
            )
        else:
            cur.execute(SCHEMA_SQL)
    conn.commit()


def get_last_ts(
    conn: psycopg.Connection, ticker: str, provider: str, interval: str
) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(ts)
            FROM price_history
            WHERE ticker = %s AND provider = %s AND interval = %s
            """,
            (ticker, provider, interval),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def get_last_date(conn: psycopg.Connection, ticker: str, provider: str) -> date | None:
    """Deprecated: use get_last_ts instead."""
    ts = get_last_ts(conn, ticker, provider, interval="1d")
    return ts.date() if ts is not None else None


def upsert_price_bars(conn: psycopg.Connection, provider: str, bars: list[PriceBar]) -> int:
    if not bars:
        return 0

    payload = [
        (
            b.ticker,
            provider,
            b.provider_symbol,
            b.interval,
            b.ts,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
        )
        for b in bars
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO price_history (
                ticker, provider, provider_symbol, interval, ts,
                open, high, low, close, volume
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, provider_symbol, interval, ts)
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                updated_at = now()
            """,
            payload,
        )
    conn.commit()
    return len(payload)


def load_close_series(
    conn: psycopg.Connection, ticker: str, provider: str, interval: str = "1d"
) -> pd.Series:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts, close
            FROM price_history
            WHERE ticker = %s AND provider = %s AND interval = %s AND close IS NOT NULL
            ORDER BY ts ASC
            """,
            (ticker, provider, interval),
        )
        rows = cur.fetchall()

    if not rows:
        return pd.Series(dtype=float)

    idx = pd.to_datetime([r[0] for r in rows], utc=True)
    values = [float(r[1]) for r in rows]
    return pd.Series(values, index=idx, dtype=float)
