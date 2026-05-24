from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from typing import Iterator

import pandas as pd
import psycopg

from .providers.base import PriceBar


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS price_history (
    ticker TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    date DATE NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_price_history_ticker_date
    ON price_history (ticker, date DESC);
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
        cur.execute(SCHEMA_SQL)
    conn.commit()


def get_last_date(conn: psycopg.Connection, ticker: str, provider: str) -> date | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(date)
            FROM price_history
            WHERE ticker = %s AND provider = %s
            """,
            (ticker, provider),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def upsert_price_bars(conn: psycopg.Connection, provider: str, bars: list[PriceBar]) -> int:
    if not bars:
        return 0

    payload = [
        (
            b.ticker,
            provider,
            b.provider_symbol,
            b.date,
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
                ticker, provider, provider_symbol, date, open, high, low, close, volume
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, provider_symbol, date)
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


def load_close_series(conn: psycopg.Connection, ticker: str, provider: str) -> pd.Series:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close
            FROM price_history
            WHERE ticker = %s AND provider = %s AND close IS NOT NULL
            ORDER BY date ASC
            """,
            (ticker, provider),
        )
        rows = cur.fetchall()

    if not rows:
        return pd.Series(dtype=float)

    idx = pd.to_datetime([r[0] for r in rows], utc=True)
    values = [float(r[1]) for r in rows]
    return pd.Series(values, index=idx, dtype=float)
