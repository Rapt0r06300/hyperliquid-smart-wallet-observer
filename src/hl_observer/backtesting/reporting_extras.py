"""Rapports & visualisation — purs, testés. Exécution du backlog :
daily_report_markdown (IMPROVE-42, rapport quotidien lisible), equity_svg (IMPROVE-45, courbe
d'equity + drawdown sans aucune dépendance), l2_feature_vector (IMPROVE-34, vecteur de features
microstructure depuis le carnet). Aucune promesse de PnL — on affiche ce qui EST. Aucun ordre.
"""
from __future__ import annotations

from hl_observer.backtesting.execution_models import effective_spread, micro_price
from hl_observer.backtesting.microstructure import kyle_lambda


def daily_report_markdown(stats: dict) -> str:
    """Rapport quotidien honnête : ce qui s'est passé, y compris les pertes et les refus."""
    net = float(stats.get("net_usd", 0.0))
    wins = int(stats.get("wins", 0))
    losses = int(stats.get("losses", 0))
    total = wins + losses
    wr = (100.0 * wins / total) if total else 0.0
    gp = float(stats.get("gross_profit", 0.0))
    gl = abs(float(stats.get("gross_loss", 0.0)))
    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
    verdict = "PERTE" if net < 0 else ("GAIN" if net > 0 else "NEUTRE")

    lines = [
        f"# Rapport quotidien — {stats.get('date', 'n/a')}",
        "",
        f"**Résultat paper : {net:+.2f} $ ({verdict})**  ·  simulation uniquement, 0 argent réel.",
        "",
        "| Métrique | Valeur |",
        "|---|---|",
        f"| Trades | {total} |",
        f"| Gagnants / Perdants | {wins} / {losses} |",
        f"| Winrate | {wr:.1f} % |",
        f"| Profit factor | {pf:.2f} |",
        f"| Frais + coûts | {float(stats.get('costs_usd', 0.0)):.2f} $ |",
        f"| Refus (NO_TRADE) | {int(stats.get('refusals', 0))} |",
        f"| Drawdown max | {float(stats.get('max_drawdown', 0.0)):.2f} $ |",
        "",
    ]
    top = stats.get("top_refusal_reasons") or {}
    if top:
        lines.append("## Pourquoi on n'a PAS tradé (top raisons)")
        lines.append("")
        for reason, n in sorted(top.items(), key=lambda kv: -kv[1])[:5]:
            lines.append(f"- `{reason}` — {n}x")
        lines.append("")
    lines.append("> Les refus ne sont pas des échecs : chaque refus est un trade à edge net négatif évité.")
    return "\n".join(lines) + "\n"


def equity_svg(equity, *, width: int = 640, height: int = 200) -> str:
    """Courbe d'equity + drawdown en SVG pur (aucune dépendance graphique)."""
    pts = [float(e) for e in equity]
    if len(pts) < 2:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>'
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    n = len(pts)

    def xy(i, v):
        x = 10 + (width - 20) * i / (n - 1)
        y = height - 20 - (height - 40) * (v - lo) / span
        return f"{x:.1f},{y:.1f}"

    line = " ".join(xy(i, v) for i, v in enumerate(pts))
    peak, dd = pts[0], 0.0
    for v in pts:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    colour = "#22c55e" if pts[-1] >= pts[0] else "#ef4444"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<polyline points="{line}" fill="none" stroke="{colour}" stroke-width="2"/>'
        f'<text x="10" y="16" font-size="12" fill="{colour}">'
        f'equity {pts[-1]:.2f} · DD max {dd:.2f}</text></svg>'
    )


def l2_feature_vector(bids, asks, *, trades=None) -> dict:
    """Vecteur de features microstructure depuis le carnet L2 : déséquilibre de profondeur,
    micro-prix, spread effectif, impact de Kyle. Prêt à alimenter un modèle."""
    if not bids or not asks:
        return {"imbalance": 0.0, "micro_price": 0.0, "spread_bps": 0.0, "kyle_lambda": 0.0}
    bid_p, bid_s = float(bids[0][0]), float(bids[0][1])
    ask_p, ask_s = float(asks[0][0]), float(asks[0][1])
    mid = (bid_p + ask_p) / 2.0
    depth = bid_s + ask_s
    feats = {
        "imbalance": (bid_s - ask_s) / depth if depth > 0 else 0.0,
        "micro_price": micro_price(bid_p, ask_p, bid_s, ask_s),
        "spread_bps": (effective_spread(ask_p, mid, "BUY") * 10000.0 / mid) if mid else 0.0,
        "kyle_lambda": 0.0,
    }
    if trades:
        feats["kyle_lambda"] = kyle_lambda([float(t[0]) for t in trades],
                                           [float(t[1]) for t in trades])
    return feats
