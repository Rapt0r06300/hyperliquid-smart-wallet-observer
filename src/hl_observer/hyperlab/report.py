"""[Bloc 56 / AUD-101,144] Rapport SIMPLE pour Flo : positions, PnL net, couts, drawdown, blocages
nommes, prochaine action. Honnete : les blocages ne sont jamais masques. deterministe."""
from __future__ import annotations

from typing import Optional, Sequence


def _drawdown(equity_series: Sequence[float]) -> float:
    peak = float("-inf")
    dd = 0.0
    for v in equity_series:
        peak = max(peak, v)
        dd = min(dd, v - peak)
    return dd


def rapport_simple(moteur, *, blocages, prochaine_action: str,
                   equity_series: Optional[Sequence[float]] = None, marks: Optional[dict] = None) -> dict:
    eq = moteur.equity(marks or {})
    positions = [{"venue": v, "symbole": s, "notionnel_net_usd": round(n, 4)}
                 for (v, s), n in sorted(moteur._expo_par_cle.items()) if abs(n) > 1e-9]
    return {"positions": positions,
            "pnl_net_usd": round(eq["equity"] - eq["capital"], 6),
            "couts_usd": round(moteur.frais_cumules, 6),
            "drawdown_usd": round(_drawdown(equity_series), 6) if equity_series else 0.0,
            "equity_usd": round(eq["equity"], 6),
            "expo_brute_usd": round(eq["expo_brute"], 4),
            "enveloppe_usd": moteur.enveloppe_usd,
            "blocages": list(blocages),
            "prochaine_action": prochaine_action}
