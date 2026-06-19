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
                if isinstance(c, dict):
                    open_time_ms = int(c["time"])
                    o, h, l, cl, vol = c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume")
                else:
                    open_time_ms = int(c[0])
                    o, h, l, cl, vol = c[1], c[2], c[3], c[4], c[5]
                ts = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
                bars.append(PriceBar(
                    ticker=symbol,
                    provider_symbol=bingx_symbol,
                    interval=interval,
                    ts=ts,
                    open=float(o) if o else None,
                    high=float(h) if h else None,
                    low=float(l) if l else None,
                    close=float(cl) if cl else None,
                    volume=float(vol) if vol else None,
                ))

            last_c = candles[-1]
            last_open_ms = int(last_c["time"] if isinstance(last_c, dict) else last_c[0])
            if last_open_ms <= cursor:
                break
            cursor = last_open_ms + 1

            if len(candles) < _MAX_LIMIT:
                break

            time.sleep(0.05)

        return bars
