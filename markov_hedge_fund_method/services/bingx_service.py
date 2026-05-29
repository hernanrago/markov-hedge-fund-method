"""BingX Perpetual Futures — open positions query.

Reuses the HMAC-SHA256 auth pattern from the antivitalik-cron-job project.
Credentials are read from env vars BINGX_API_KEY / BINGX_API_SECRET.
Returns {bingx_symbol: "Long"/"Short"} for all positions with nonzero size.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import requests

BASE_URL = "https://open-api.bingx.com"


def _sign(secret: str, params_str: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        params_str.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _params_str(params: dict) -> str:
    return "&".join(f"{k}={v}" for k, v in params.items())


def get_all_positions(api_key: str | None = None, api_secret: str | None = None) -> dict[str, str]:
    """Fetch all open perpetual positions from BingX.

    Returns a dict mapping BingX symbol (e.g. "BTC-USDT") to "Long" or "Short".
    Only positions with nonzero positionAmt are included.
    Raises RuntimeError on API error or missing credentials.
    """
    key = api_key or os.environ.get("BINGX_API_KEY", "")
    secret = api_secret or os.environ.get("BINGX_API_SECRET", "")
    if not key or not secret:
        raise RuntimeError("BINGX_API_KEY and BINGX_API_SECRET are required")

    endpoint = "/openApi/swap/v2/user/positions"
    params = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    ps = _params_str(params)
    sig = _sign(secret, ps)
    url = f"{BASE_URL}{endpoint}?{ps}&signature={sig}"
    headers = {"X-BX-APIKEY": key}

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"BingX API error {data.get('code')}: {data.get('msg')}")

    result: dict[str, str] = {}
    for pos in data.get("data", []):
        amt = float(pos.get("positionAmt", 0))
        if amt == 0:
            continue
        symbol = pos.get("symbol", "")
        if not symbol:
            continue
        side_raw = pos.get("positionSide", "")
        if side_raw in ("LONG", "SHORT"):
            direction = "Long" if side_raw == "LONG" else "Short"
        else:
            direction = "Long" if amt > 0 else "Short"
        result[symbol] = direction

    return result
