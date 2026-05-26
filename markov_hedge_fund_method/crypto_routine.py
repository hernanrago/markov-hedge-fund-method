"""Daily crypto routine — pure Python, zero Claude tokens.

Runs the Markov regime model on a list of tickers, prints a summary table,
and optionally sends an HTML email via Gmail SMTP.

Usage:
    python -m markov_hedge_fund_method.crypto_routine \
        --tickers BTC-USD,ETH-USD,SOL-USD \
        --years 2

Env vars (all optional — email is skipped if not set):
    EMAIL_TO        Recipient address
    SMTP_USER       Gmail address used to send
    SMTP_PASSWORD   Gmail App Password (16-char, no spaces)
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .providers import get_provider
from .regime import (
    STATES,
    build_transition_matrix,
    label_regimes,
    stationary_distribution,
    walk_forward_backtest,
)
from .services.data_service import DataService

# Load .env if present (local dev); Railway injects env vars directly
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


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


def fetch(ticker: str, years: int, interval: str = "1d") -> pd.DataFrame:
    import yfinance as yf
    end = pd.Timestamp.now(tz="UTC").normalize()
    max_days = _MAX_LOOKBACK_DAYS.get(interval, 720)
    actual_days = min(years * 365, max_days)
    start = end - pd.Timedelta(days=actual_days)
    for attempt in (1, 2):
        try:
            df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"), interval=interval,
                             progress=False, auto_adjust=True)
        except Exception:
            df = pd.DataFrame()
        if not df.empty:
            return df
        if attempt == 1:
            time.sleep(15)
    return pd.DataFrame()


def _legacy_close_series_from_yahoo(ticker: str, years: int, interval: str = "1d") -> pd.Series:
    df = fetch(ticker, years, interval)
    if df.empty:
        return pd.Series(dtype=float)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()


def analyze(ticker: str, years: int, window: int, threshold: float, interval: str = "1d") -> dict:
    close = pd.Series(dtype=float)
    ingest_meta: dict = {}
    db_enabled = bool(os.environ.get("DATABASE_URL"))

    defaults = _INTERVAL_DEFAULTS.get(interval, _INTERVAL_DEFAULTS["1d"])
    bars_per_year = defaults["bars_per_year"]
    min_train = defaults["min_train"]

    if db_enabled:
        try:
            provider = get_provider()
            service = DataService(provider=provider)
            close, ingest_meta = service.get_close_series(ticker=ticker, years=years, interval=interval)
        except Exception as exc:  # noqa: BLE001
            ingest_meta = {"provider": "fallback", "error": str(exc)}

    if close.empty:
        close = _legacy_close_series_from_yahoo(ticker, years, interval)

    if close.empty:
        return {"ticker": ticker, "error": "no data from market data provider"}

    labels = label_regimes(close, window=window, threshold=threshold)
    if labels.empty:
        return {"ticker": ticker, "error": f"insufficient data after regime labeling ({len(close)} bars)"}

    P = build_transition_matrix(labels)
    pi = stationary_distribution(P)
    result = walk_forward_backtest(close, labels, min_train=min_train, bars_per_year=bars_per_year)

    current_state = int(labels.iloc[-1])
    current_regime = STATES[current_state]

    return {
        "ticker": ticker,
        "current_regime": current_regime,
        "p_bull": float(P[current_state, 2]),
        "p_sideways": float(P[current_state, 1]),
        "p_bear": float(P[current_state, 0]),
        "sharpe": result["sharpe"],
        "stationary_bull": float(pi[2]),
        "rows": len(close),
        "ingest_meta": ingest_meta,
        "error": None,
    }


# ── CLI output ────────────────────────────────────────────────────────────────

def print_table(results: list[dict], timestamp: str) -> list[dict]:
    """Print ASCII table, return list of HIGH RISK results."""
    print(f"\nMarkov Crypto Regime Report — {timestamp}")
    print("=" * 80)
    print(f"{'Ticker':<10} {'Regime':<10} {'P(Bull)':>8} {'P(Bear)':>8} {'Sharpe':>8}  {'Flag'}")
    print("-" * 80)

    high_risk = []
    for r in results:
        if r.get("error"):
            print(f"  {r['ticker']:<10} ERROR: {r['error']}")
            continue
        sharpe_str = f"{r['sharpe']:.3f}" if np.isfinite(r["sharpe"]) else "   N/A"
        flag = ""
        if r["p_bear"] > 0.60:
            flag = "HIGH RISK"
            high_risk.append(r)
        print(
            f"  {r['ticker']:<10} {r['current_regime']:<10} "
            f"{r['p_bull']*100:>7.1f}% {r['p_bear']*100:>7.1f}% "
            f"{sharpe_str:>8}  {flag}"
        )

    print("=" * 80)
    if high_risk:
        print(f"HIGH RISK: {', '.join(r['ticker'] for r in high_risk)}")
    else:
        print("No HIGH RISK tickers detected.")
    print()
    return high_risk


# ── HTML email ────────────────────────────────────────────────────────────────

def _regime_color(regime: str) -> str:
    return {"Bull": "#15803d", "Bear": "#dc2626", "Sideways": "#d97706"}.get(regime, "#334155")


def _row_html(r: dict) -> str:
    sharpe_str = f"{r['sharpe']:.3f}" if np.isfinite(r["sharpe"]) else "N/A"
    flag = "🔴 HIGH RISK" if r["p_bear"] > 0.60 else ""
    regime_color = _regime_color(r["current_regime"])
    rows = [
        ("Régimen actual", f'<span style="color:{regime_color};font-weight:bold;">{r["current_regime"]}</span>'),
        ("P(Bull mañana)", f"{r['p_bull']*100:.1f}%"),
        ("P(Bear mañana)", f"{r['p_bear']*100:.1f}%"),
        ("P(Sideways)",    f"{r['p_sideways']*100:.1f}%"),
        ("Sharpe WF",      sharpe_str),
        ("Flag",           flag),
    ]
    rows_html = "".join(
        f'<tr style="background:{"#f8fafc" if i % 2 == 0 else "#ffffff"};">'
        f'<td style="padding:6px 12px;color:#64748b;white-space:nowrap;">{label}</td>'
        f'<td style="padding:6px 12px;font-size:13px;">{value}</td>'
        f"</tr>"
        for i, (label, value) in enumerate(rows)
        if value
    )
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-family:monospace;font-size:13px;">
      <thead>
        <tr style="background:#1e293b;color:#f1f5f9;">
          <th colspan="2" style="padding:10px 14px;text-align:left;">{r['ticker']}</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>"""


def build_html(results: list[dict], timestamp: str, config: dict | None = None) -> str:
    ok = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]
    cards = "".join(_row_html(r) for r in ok)
    error_html = ""
    if errors:
        error_html = "<p style='color:#dc2626;font-size:12px;'>Errores: " + \
                     ", ".join(f"{r['ticker']} ({r['error']})" for r in errors) + "</p>"
    high_risk = [r for r in ok if r["p_bear"] > 0.60]
    summary = f"<strong>{len(high_risk)} HIGH RISK</strong>" if high_risk else "Sin alertas HIGH RISK"

    config_html = ""
    if config:
        style_part = f"style={config['style']} · " if config.get("style") else ""
        config_html = (
            f"<p style='margin:0 0 20px;color:#94a3b8;font-size:11px;'>"
            f"{style_part}years={config['years']} · interval={config['interval']} · window={config['window']}"
            f"</p>"
        )

    return f"""
    <div style="font-family:sans-serif;max-width:680px;margin:auto;padding:24px;background:#ffffff;">
      <h2 style="margin:0 0 4px;color:#0f172a;">Markov Crypto Report</h2>
      <p style="margin:0 0 6px;color:#64748b;font-size:13px;">{timestamp}</p>
      {config_html}
      <p style="margin:0 0 24px;font-size:13px;color:#334155;">{summary}</p>
      {cards}
      {error_html}
      <p style="margin-top:24px;color:#94a3b8;font-size:11px;text-align:center;">
        markov-hedge-fund-method · Railway cron
      </p>
    </div>"""


def send_email_smtp(subject: str, html: str) -> None:
    email_to   = os.environ["EMAIL_TO"]
    smtp_user  = os.environ["SMTP_USER"]
    smtp_pass  = os.environ["SMTP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = email_to
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(smtp_user, smtp_pass)
        smtp.sendmail(smtp_user, email_to, msg.as_string())

    print(f"Email enviado → {email_to}")


def send_email_resend(subject: str, html: str) -> None:
    api_key = os.environ["RESEND_API_KEY"]
    email_to = os.environ["EMAIL_TO"]
    email_from = os.environ.get("EMAIL_FROM", "Markov Report <onboarding@resend.dev>")

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": email_from,
            "to": [email_to],
            "subject": subject,
            "html": html,
        },
        timeout=20,
    )
    response.raise_for_status()
    print(f"Email enviado via Resend → {email_to}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(prog="crypto-routine")
    parser.add_argument("--tickers", default="BTC-USD,ETH-USD,SOL-USD,XRP-USD,DOGE-USD,BNB-USD,SUI-USD,ADA-USD,AVAX-USD,LINK-USD,NEAR-USD,TON-USD,TRX-USD,LTC-USD,BCH-USD,HYPE-USD")
    parser.add_argument("--years",     type=int,   default=None)
    parser.add_argument("--window",    type=int,   default=None,
        help="Rolling window in bars (default: auto from --interval or --style)")
    parser.add_argument("--threshold", type=float, default=0.02)
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
    years = args.years if args.years is not None else preset.get("years", 2)
    window = args.window if args.window is not None else preset.get("window", _INTERVAL_DEFAULTS.get(interval, _INTERVAL_DEFAULTS["1d"])["window"])

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    style_label = f", style={args.style}" if args.style else ""
    print(f"Running Markov model on {len(tickers)} tickers (years={years}, window={window}, interval={interval}{style_label})...")
    results = []
    for ticker in tickers:
        print(f"  {ticker}...", end=" ", flush=True)
        r = analyze(ticker, years, window, args.threshold, interval=interval)
        results.append(r)
        print("ok" if not r.get("error") else f"SKIP ({r['error']})")
        if r.get("ingest_meta"):
            meta = r["ingest_meta"]
            provider = meta.get("provider", "unknown")
            rows_fetched = meta.get("rows_fetched", "n/a")
            rows_upserted = meta.get("rows_upserted", "n/a")
            print(
                f"    provider={provider} rows_fetched={rows_fetched} rows_upserted={rows_upserted}"
            )

    print_table(results, timestamp)

    if not os.environ.get("RESEND_API_KEY") and not os.environ.get("SMTP_USER"):
        print("Ni RESEND_API_KEY ni SMTP_USER configurados — email omitido.")
        return 0

    high_risk = [r for r in results if not r.get("error") and r["p_bear"] > 0.60]
    subject = (
        f"🔴 Markov Crypto — {len(high_risk)} HIGH RISK: {', '.join(r['ticker'] for r in high_risk)}"
        if high_risk
        else f"✅ Markov Crypto Report — {timestamp}"
    )
    html = build_html(results, timestamp, config={"style": args.style, "years": years, "interval": interval, "window": window})

    try:
        if os.environ.get("RESEND_API_KEY"):
            send_email_resend(subject, html)
        elif os.environ.get("SMTP_USER"):
            send_email_smtp(subject, html)
    except Exception as exc:  # noqa: BLE001
        print(f"Email no enviado: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
