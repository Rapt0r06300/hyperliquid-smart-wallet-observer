"""SIZING LIQUIDATION (idées #10/#11) — dimensionner le fade selon l'ampleur de la purge, et
détecter le combo liquidation+funding. Pur, deny-by-default. PAPER only, aucun ordre.

  Y10 facteur_taille_cascade : plus la liquidation forcée est GROSSE (notional), plus le rebond est
      net -> taille proportionnelle, bornée. En dessous d'un plancher de purge -> 0 (pas une vraie purge).
  Y11 combo_liquidation_funding : une cascade coïncide souvent avec un choc de funding (deleveraging
      forcé). Quand les deux sont présents et dans le MÊME sens, la conviction monte.
"""
from __future__ import annotations

NOTIONNEL_PURGE_MIN_USD = 50_000.0     # sous ça, pas une vraie purge -> pas de trade
NOTIONNEL_PURGE_REF_USD = 1_000_000.0  # purge "pleine taille" (1 M$) -> facteur 1.0
FUNDING_CHOC_MIN_BPS_H = 0.5           # choc de funding significatif


def facteur_taille_cascade(notionnel_purge_usd: float | None, *,
                           mini: float = NOTIONNEL_PURGE_MIN_USD,
                           ref: float = NOTIONNEL_PURGE_REF_USD, plafond: float = 1.5) -> float:
    """Facteur de taille du fade (0 si pas une purge, sinon proportionnel au notional, borné)."""
    if notionnel_purge_usd is None or float(notionnel_purge_usd) < float(mini):
        return 0.0
    return max(0.0, min(float(plafond), float(notionnel_purge_usd) / float(ref)))


def combo_liquidation_funding(direction_liquidation: str | None, funding_bps_h: float | None, *,
                              choc_min_bps_h: float = FUNDING_CHOC_MIN_BPS_H) -> dict:
    """Y11 : conviction renforcée si une purge ET un choc de funding pointent dans le même sens.
    LONG relâché (longs liquidés) + funding devenu très NÉGATIF (shorts payés) = double signal haussier."""
    d = str(direction_liquidation or "").upper()
    f = float(funding_bps_h) if funding_bps_h is not None else 0.0
    choc = abs(f) >= float(choc_min_bps_h)
    aligne = (d == "LONG" and f < 0) or (d == "SHORT" and f > 0)
    return {"choc_funding": choc, "aligne": bool(choc and aligne),
            "facteur_conviction": 1.3 if (choc and aligne) else 1.0}


__all__ = ["facteur_taille_cascade", "combo_liquidation_funding",
           "NOTIONNEL_PURGE_MIN_USD", "NOTIONNEL_PURGE_REF_USD", "FUNDING_CHOC_MIN_BPS_H"]
