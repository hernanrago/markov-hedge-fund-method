"""Position alignment between BingX open positions and Markov report bias.

Mapping:
    Bull  → Long
    Bear  → Short
    Sideways → Neutral (no directional bias)

Ticker normalization: Yahoo Finance uses USD suffix (BTC-USD),
BingX uses USDT (BTC-USDT).
"""
from __future__ import annotations

REGIME_TO_DIRECTION: dict[str, str | None] = {
    "Bull": "Long",
    "Bear": "Short",
    "Sideways": None,
}


def yahoo_to_bingx(ticker: str) -> str:
    """Convert Yahoo Finance ticker to BingX symbol: BTC-USD → BTC-USDT."""
    if ticker.endswith("-USD"):
        return ticker[:-4] + "-USDT"
    return ticker


def build_alignment_rows(
    results: list[dict],
    positions: dict[str, str],
) -> list[dict]:
    """Compare Markov report regimes against open BingX positions.

    Args:
        results:   list of analyze() dicts (only tickers without errors are used)
        positions: {bingx_symbol: "Long"/"Short"} from bingx_service.get_all_positions()

    Returns:
        list of dicts with keys:
            symbol            – BingX symbol (e.g. "BTC-USDT")
            current_direction – "Long" or "Short" (from BingX)
            report_direction  – "Long", "Short", or "Neutral" (from Markov regime)
            aligned           – "Alineado", "Desalineado", or "Neutral"
    """
    rows = []
    for r in results:
        if r.get("error"):
            continue
        bingx_symbol = yahoo_to_bingx(r["ticker"])
        if bingx_symbol not in positions:
            continue
        current_dir = positions[bingx_symbol]
        report_dir = REGIME_TO_DIRECTION.get(r["current_regime"])
        if report_dir is None:
            status = "Neutral"
        else:
            status = "Alineado" if current_dir == report_dir else "Desalineado"
        rows.append({
            "symbol": bingx_symbol,
            "current_direction": current_dir,
            "report_direction": report_dir or "Neutral",
            "aligned": status,
        })
    return rows


def _dir_color(d: str) -> str:
    return {"Long": "#15803d", "Short": "#dc2626", "Neutral": "#d97706"}.get(d, "#334155")


def _status_badge(status: str) -> str:
    if status == "Alineado":
        return '<span style="color:#15803d;font-weight:bold;">✓ Alineado</span>'
    if status == "Desalineado":
        return '<span style="color:#dc2626;font-weight:bold;">✗ Desalineado</span>'
    return '<span style="color:#d97706;">— Neutral</span>'


def render_alignment_table_html(rows: list[dict]) -> str:
    """Render the alignment comparison as an HTML table section."""
    if not rows:
        return ""

    th = "padding:8px 14px;text-align:left;font-weight:bold;"
    td = "padding:6px 14px;font-size:13px;"

    header = (
        f'<tr style="background:#1e293b;color:#f1f5f9;">'
        f'<th style="{th}">Símbolo</th>'
        f'<th style="{th}">Posición BingX</th>'
        f'<th style="{th}">Sesgo Reporte</th>'
        f'<th style="{th}">Estado</th>'
        f'</tr>'
    )

    body_rows = ""
    for i, row in enumerate(rows):
        bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
        body_rows += (
            f'<tr style="background:{bg};">'
            f'<td style="{td}font-weight:bold;">{row["symbol"]}</td>'
            f'<td style="{td}color:{_dir_color(row["current_direction"])};">{row["current_direction"]}</td>'
            f'<td style="{td}color:{_dir_color(row["report_direction"])};">{row["report_direction"]}</td>'
            f'<td style="{td}">{_status_badge(row["aligned"])}</td>'
            f'</tr>'
        )

    desalineados = sum(1 for r in rows if r["aligned"] == "Desalineado")
    summary_color = "#dc2626" if desalineados else "#15803d"
    summary_text = (
        f'<strong style="color:{summary_color};">{desalineados} posición(es) desalineada(s)</strong>'
        if desalineados
        else '<strong style="color:#15803d;">Todas las posiciones alineadas</strong>'
    )

    return (
        f'<h3 style="margin:32px 0 4px;color:#0f172a;font-size:14px;">Alineación BingX vs Reporte</h3>'
        f'<p style="margin:0 0 8px;font-size:12px;color:#64748b;">{summary_text}</p>'
        f'<table style="width:100%;border-collapse:collapse;font-family:monospace;font-size:13px;">'
        f'<thead>{header}</thead>'
        f'<tbody>{body_rows}</tbody>'
        f'</table>'
    )
