"""CLI entry point: fetch -> label -> matrix -> stationary -> walk-forward.

Usage:
    uv run python -m markov_hedge_fund_method.run --ticker SPY --style swing
    uv run python -m markov_hedge_fund_method.run --ticker BTC-USD --years 2 --interval 1h
    uv run python -m markov_hedge_fund_method.run --ticker SPY --years 10 --interval 1d

Trading style presets (--style):
    position       years=10  interval=1d  window=250  (macro trend following)
    swing          years=6   interval=1d  window=150  (balanced, good default)
    swing-intraday years=5   interval=4h  window=200  (short swing / intraday)
    day            years=3   interval=1h  window=150  (day trading)
    day-active     years=2   interval=15m window=115  (active day trading)
    scalping       years=1   interval=5m  window=90   (scalping)

Note: bars_per_year defaults assume 24/7 crypto trading. For equities use --interval 1d.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .regime import (
    STATES,
    label_regimes,
    build_transition_matrix,
    stationary_distribution,
    walk_forward_backtest,
)

HMM_FLAG_FILE = Path(__file__).resolve().parent.parent / ".hmm_available"

_INTERVAL_DEFAULTS: dict[str, dict] = {
    "1d":  {"bars_per_year": 252,    "window": 20,   "min_train": 252},
    "1h":  {"bars_per_year": 8760,   "window": 168,  "min_train": 2016},
    "4h":  {"bars_per_year": 2190,   "window": 42,   "min_train": 504},
    "15m": {"bars_per_year": 35040,  "window": 672,  "min_train": 2016},
    "5m":  {"bars_per_year": 105120, "window": 2016, "min_train": 6048},
}

_STYLE_PRESETS: dict[str, dict] = {
    "position":       {"years": 10, "interval": "1d",  "window": 250},
    "swing":          {"years":  6, "interval": "1d",  "window": 150},
    "swing-intraday": {"years":  5, "interval": "4h",  "window": 200},
    "day":            {"years":  3, "interval": "1h",  "window": 150},
    "day-active":     {"years":  2, "interval": "15m", "window": 115},
    "scalping":       {"years":  1, "interval": "5m",  "window":  90},
}

_MAX_LOOKBACK_DAYS: dict[str, int] = {
    "1m": 7, "5m": 60, "15m": 60, "30m": 60,
    "1h": 720, "4h": 720, "1d": 36500,
}


def _hmm_available() -> bool:
    if HMM_FLAG_FILE.exists():
        return HMM_FLAG_FILE.read_text().strip().lower() == "true"
    try:
        import hmmlearn  # noqa: F401
        return True
    except ImportError:
        return False


def _fetch_with_retry(ticker: str, years: int, interval: str = "1d") -> pd.DataFrame:
    import yfinance as yf

    end = pd.Timestamp.now(tz="UTC").normalize()
    max_days = _MAX_LOOKBACK_DAYS.get(interval, 730)
    actual_days = min(years * 365, max_days)
    start = end - pd.Timedelta(days=actual_days)

    for attempt in (1, 2):
        try:
            df = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! yfinance error on attempt {attempt}: {exc}")
            df = pd.DataFrame()

        if not df.empty:
            return df

        if attempt == 1:
            print("  ! yfinance returned empty data — retrying in 30s.")
            time.sleep(30)

    raise RuntimeError(
        f"yfinance returned empty data for {ticker} after retry. "
        "Yahoo may be rate-limiting. Try again in a few minutes."
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="markov-hedge-fund-method")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--years", type=int, default=None)
    parser.add_argument("--window", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=0.02)
    parser.add_argument("--no-hmm", action="store_true")
    parser.add_argument(
        "--interval", default=None,
        choices=["1d", "1h", "4h", "15m", "5m"],
        help="Bar interval. 1h/4h: up to 720 days history from Yahoo Finance.",
    )
    parser.add_argument(
        "--style", default=None,
        choices=list(_STYLE_PRESETS),
        help="Trading style preset (sets --years/--interval/--window defaults). "
             "Explicit flags override preset values.",
    )
    args = parser.parse_args()

    preset = _STYLE_PRESETS.get(args.style, {}) if args.style else {}
    interval = args.interval or preset.get("interval", "1d")
    years = args.years if args.years is not None else preset.get("years", 10)

    defaults = _INTERVAL_DEFAULTS.get(interval, _INTERVAL_DEFAULTS["1d"])
    window = args.window if args.window is not None else preset.get("window", defaults["window"])
    bars_per_year = defaults["bars_per_year"]
    min_train = defaults["min_train"]

    style_label = f" style={args.style}" if args.style else ""
    print(f"\nmarkov-hedge-fund-method — ticker={args.ticker} years={years} window={window} interval={interval}{style_label}")
    print(f"  fetching {args.ticker} from Yahoo Finance...")
    df = _fetch_with_retry(args.ticker, years, interval=interval)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna()
    print(f"  fetched {len(close)} rows | {close.index.min().date()} -> {close.index.max().date()}")

    labels = label_regimes(close, window=window, threshold=args.threshold)
    P = build_transition_matrix(labels)
    pi = stationary_distribution(P)

    print("\nTransition matrix (rows = from, cols = to):")
    print(f"            {STATES[0]:>9s} {STATES[1]:>9s} {STATES[2]:>9s}")
    for i, from_state in enumerate(STATES):
        row = "  ".join(f"{P[i, j]*100:7.2f}%" for j in range(3))
        print(f"  {from_state:>9s}  {row}")

    print("\nPersistence diagonal:")
    print(f"  {STATES[0]} -> {STATES[0]}: {P[0,0]*100:.2f}%")
    print(f"  {STATES[1]} -> {STATES[1]}: {P[1,1]*100:.2f}%")
    print(f"  {STATES[2]} -> {STATES[2]}: {P[2,2]*100:.2f}%")

    print("\nStationary distribution (long-run regime mix):")
    for s, p in zip(STATES, pi):
        print(f"  {s:>9s}: {p*100:.2f}%")

    print("\nWalk-forward backtest (re-estimating matrix at every step, no lookahead)...")
    result = walk_forward_backtest(close, labels, min_train=min_train, bars_per_year=bars_per_year)
    sharpe = result["sharpe"]
    mdd = result["max_drawdown"]
    if np.isfinite(sharpe):
        print(f"  Sharpe (annualised, walk-forward): {sharpe:.3f}")
    else:
        print("  Sharpe: NaN (insufficient data — try a longer history or different ticker)")
    if np.isfinite(mdd):
        print(f"  Max drawdown:                       {mdd*100:.2f}%")
    else:
        print("  Max drawdown: NaN")
    print(f"  Periods evaluated: {result['n_periods']}")

    if not args.no_hmm and _hmm_available():
        print("\nFitting Hidden Markov Model (Baum-Welch + Viterbi via hmmlearn)...")
        try:
            from .hmm_extension import fit_hmm
            returns = close.pct_change().dropna()
            model, hidden = fit_hmm(returns, n_components=3)
            if model is None:
                print("  HMM extension skipped (hmmlearn import failed at runtime).")
            else:
                means = np.array([model.means_[k][0] for k in range(model.n_components)])
                order = np.argsort(means)
                labels_for_hmm = ["Bear (lowest mean return)", "Sideways", "Bull (highest mean return)"]
                print("  HMM regime mean daily returns (sorted):")
                for rank, k in enumerate(order):
                    print(f"    {labels_for_hmm[rank]:<30s} state {k}: {means[k]*100:+.3f}% per day")
                print("  Note: Baum-Welch finds local maxima. For production fit several random_state values.")
        except Exception as exc:  # noqa: BLE001
            print(f"  HMM extension skipped at runtime: {exc}")
    else:
        print("\nHMM extension skipped (optional); observable Markov model installed successfully.")

    print("\n----------------------------------------------------------------")
    print(" Framework: Roan (@RohOnChain). Installed as a Claude Code skill")
    print(" by Lewis Jackson. Backtests are historical, not forward-looking.")
    print("----------------------------------------------------------------\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
