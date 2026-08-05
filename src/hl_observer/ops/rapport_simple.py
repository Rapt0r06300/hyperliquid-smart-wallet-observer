"""AUD-144 — rapport SIMPLE pour Flo (verdict + chiffres cles + prochaine action, une ligne).

Resume court, lisible, sans jargon. Aucune donnee fabriquee : on ne formate que ce qu'on recoit ;
un PnL non mesurable est dit UNMEASURABLE, jamais 0. Read-only.
"""
from __future__ import annotations


def rapport_simple(*, verdict: str, pnl_net: float | None, n_trades: int, prochaine_action: str) -> str:
    pnl = "n/d (UNMEASURABLE)" if pnl_net is None else ("%+.2f USD" % float(pnl_net))
    return ("VERDICT: %s | PnL net: %s | trades: %d | prochaine action: %s"
            % (str(verdict), pnl, int(n_trades), str(prochaine_action)))


__all__ = ["rapport_simple"]
