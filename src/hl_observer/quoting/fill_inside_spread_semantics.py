"""[EXECUTION lot2 #88] FILL-INSIDE-SPREAD SEMANTICS CONFIGURABLE : un ordre limit posté AU ou À L'INTÉRIEUR du
spread ne doit PAS avoir une hypothèse UNIVERSELLE de fill. Selon la venue et le régime, un tel ordre peut ne pas
être rempli immédiatement. On rend l'hypothèse EXPLICITEMENT configurable (Nautilus) : PESSIMISTE (pas de fill tant
que le marché ne vient pas), OPTIMISTE (fill si à l'intérieur), ou AUCUN. Défaut : pessimiste. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

PESSIMISTE = "PESSIMISTE"
OPTIMISTE = "OPTIMISTE"
AUCUN = "AUCUN"


def remplit(prix_limit: Any, meilleur_bid: Any, meilleur_ask: Any, sens: Any, *,
            mode: str = PESSIMISTE) -> dict[str, Any]:
    """Décide si un limit à l'intérieur du spread est réputé rempli, SELON le mode configuré. En PESSIMISTE, on ne
    suppose un fill que si l'ordre croise réellement (achat ≥ ask, vente ≤ bid). En OPTIMISTE, un ordre à
    l'intérieur du spread est réputé rempli. AUCUN → jamais de fill supposé. Prix invalide → pas de fill."""
    if not all(isinstance(x, (int, float)) for x in (prix_limit, meilleur_bid, meilleur_ask)):
        return {"rempli": False, "raison": "PRIX_INVALIDE"}
    s = str(sens).upper()
    achat = s in ("ACHAT", "BUY", "LONG")
    croise = (float(prix_limit) >= float(meilleur_ask)) if achat else (float(prix_limit) <= float(meilleur_bid))
    m = str(mode).upper()
    if m == AUCUN:
        return {"rempli": False, "mode": AUCUN, "raison": "AUCUN_FILL_SUPPOSE"}
    if m == OPTIMISTE:
        dans_spread = float(meilleur_bid) <= float(prix_limit) <= float(meilleur_ask)
        rempli = croise or dans_spread
        return {"rempli": bool(rempli), "mode": OPTIMISTE, "raison": ("REMPLI" if rempli else "HORS_SPREAD")}
    # PESSIMISTE (défaut) : seul un croisement réel remplit
    return {"rempli": bool(croise), "mode": PESSIMISTE,
            "raison": ("CROISE_DONC_REMPLI" if croise else "INSIDE_SPREAD_PAS_DE_FILL")}


__all__ = ["remplit", "PESSIMISTE", "OPTIMISTE", "AUCUN"]
