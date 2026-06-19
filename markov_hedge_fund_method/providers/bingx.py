"""BingX Perpetual Futures — public klines/OHLCV provider.

No authentication required for market data.
Endpoint: GET /openApi/swap/v3/quote/klines
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from .base import PriceBar

_BASE_URL = "https://open-api.bingx.com"
_KLINES_PATH = "/openApi/swap/v3/quote/klines"
_MAX_LIMIT = 1440

_TICKER_OVERRIDES: dict[str, str] = {
    "PEPE-USD": "1000PEPE-USDT",
    "BONK-USD": "1000BONK-USDT",
}


def _to_bingx_symbol(ticker: str) -> str:
    if ticker in _TICKER_OVERRIDES:
        return _TICKER_OVERRIDES[ticker]
    if ticker.endswith("-USD"):
        return ticker[:-4] + "-USDT"
    return ticker


class BingXProvider:
    def name(self) -> str:
        return "bingx"

    def fetch_history(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> list[PriceBar]:
        bingx_symbol = _to_bingx_symbol(symbol)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        bars: list[PriceBar] = []
        cursor = start_ms

        while cursor < end_ms:
            params = {
                "symbol": bingx_symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": _MAX_LIMIT,
            }
            resp = requests.get(
                f"{_BASE_URL}{_KLINES_PATH}",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                raise RuntimeError(
                    f"BingX klines error {payload.get('code')}: {payload.get('msg')}"
                )

            candles = payload.get("data") or []
            if not candles:
                break

            for c in candles:
                open_time_ms = int(c[0])
                ts = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
                bars.append(PriceBar(
                    ticker=symbol,
                    provider_symbol=bingx_symbol,
                    interval=interval,
                    ts=ts,
                    open=float(c[1]) if c[1] else None,
                    high=float(c[2]) if c[2] else None,
                    low=float(c[3]) if c[3] else None,
                    close=float(c[4]) if c[4] else None,
                    volume=float(c[5]) if c[5] else None,
                ))

            last_open_ms = int(candles[-1][0])
            if last_open_ms <= cursor:
                break
            cursor = last_open_ms + 1

            if len(candles) < _MAX_LIMIT:
                break

            time.sleep(0.05)

        return bars
