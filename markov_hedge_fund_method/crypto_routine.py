"""Daily crypto routine — pure Python, zero Claude tokens.

Runs the Markov regime model on a list of tickers and prints a summary table.
All parsing, table formatting, and HIGH RISK flagging happens in Python.

Usage:
    python -m markov_hedge_fund_method.crypto_routine \
        --tickers BTC-USD,ETH-USD,SOL-USD \
        --years 2
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .regime import label_regimes, build_transition_matrix, stationary_distribution, walk_forward_backtest, STATES


def fetch(ticker: str, years: int) -> pd.DataFrame:
    import yfinance as yf
    end = pd.Timestamp.now(tz="UTC").normalize()
    start = end - pd.DateOffset(years=years)
    for attempt in (1, 2):
        try:
            df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        except Exception:
            df = pd.DataFrame()
        if not df.empty:
            return df
        if attempt == 1:
            time.sleep(15)
    return pd.DataFrame()


def analyze(ticker: str, years: int, window: int, threshold: float) -> dict:
    df = fetch(ticker, years)
    if df.empty:
        return {"ticker": ticker, "error": "no data from Yahoo Finance"}

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna()

    labels = label_regimes(close, window=window, threshold=threshold)
    P = build_transition_matrix(labels)
    pi = stationary_distribution(P)
    result = walk_forward_backtest(close, labels)

    current_state = int(labels.iloc[-1])
    current_regime = STATES[current_state]
    p_bear = float(P[current_state, 0])
    p_sideways = float(P[current_state, 1])
    p_bull = float(P[current_state, 2])
    sharpe = result["sharpe"]

    return {
        "ticker": ticker,
        "current_regime": current_regime,
        "p_bull": p_bull,
        "p_sideways": p_sideways,
        "p_bear": p_bear,
        "sharpe": sharpe,
        "stationary_bull": float(pi[2]),
        "rows": len(close),
        "error": None,
    }


def print_table(results: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nMarkov Crypto Regime Report — {now}")
    print("=" * 80)
    header = f"{'Ticker':<10} {'Regime':<10} {'P(Bull)':>8} {'P(Bear)':>8} {'Sharpe':>8}  {'Flag'}"
    print(header)
    print("-" * 80)

    high_risk = []
    for r in results:
        if r.get("error"):
            print(f"  {r['ticker']:<10} ERROR: {r['error']}")
            continue
        sharpe_str = f"{r['sharpe']:.3f}" if np.isfinite(r["sharpe"]) else "  N/A"
        flag = ""
        if r["p_bear"] > 0.60:
            flag = "HIGH RISK"
            high_risk.append(r["ticker"])
        print(
            f"  {r['ticker']:<10} {r['current_regime']:<10} "
            f"{r['p_bull']*100:>7.1f}% {r['p_bear']*100:>7.1f}% "
            f"{sharpe_str:>8}  {flag}"
        )

    print("=" * 80)
    if high_risk:
        print(f"HIGH RISK tickers (P(Bear) > 60%): {', '.join(high_risk)}")
    else:
        print("No HIGH RISK tickers detected.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(prog="crypto-routine")
    parser.add_argument("--tickers", default="BTC-USD,ETH-USD,SOL-USD,ZEC-USD,XRP-USD,DOGE-USD,NEAR-USD,BNB-USD,SUI-USD")
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--window", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.02)
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    print(f"Running Markov model on {len(tickers)} tickers (years={args.years}, window={args.window})...")

    results = []
    for ticker in tickers:
        print(f"  {ticker}...", end=" ", flush=True)
        r = analyze(ticker, args.years, args.window, args.threshold)
        results.append(r)
        print("ok" if not r.get("error") else f"SKIP ({r['error']})")

    print_table(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
