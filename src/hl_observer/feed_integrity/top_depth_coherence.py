"""[DATA pépite 270] TOP/DEPTH COHERENCE : le BBO (top-of-book) et le sommet du L2 (depth) issus d'une MÊME
source doivent être cohérents — mêmes meilleurs prix — dans une tolérance temporelle STRICTE. Si le sommet du
L2 ne correspond pas au BBO, ou si les deux snapshots sont trop éloignés dans le temps, l'ensemble est jugé
incohérent (à ne pas exploiter comme un état unifié). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

COHERENT = "COHERENT"
INCOHERENT = "INCOHERENT"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def verifier_coherence(bbo_bid: Any, bbo_ask: Any, l2_bid_top: Any, l2_ask_top: Any, *,
                       ts_bbo: Any, ts_l2: Any, tolerance_ms: float = 50.0,
                       tolerance_prix: float = 0.0) -> dict[str, Any]:
    """Cohérent si |ts_bbo - ts_l2| ≤ tolerance_ms ET sommet L2 == BBO (à tolerance_prix près). Toute entrée
    non finie → INCOHERENT (prudence). tolerance_prix permet d'absorber un arrondi de tick documenté."""
    vals = (bbo_bid, bbo_ask, l2_bid_top, l2_ask_top, ts_bbo, ts_l2)
    if not all(_fini(v) for v in vals):
        return {"etat": INCOHERENT, "raison": "VALEUR_NON_NUMERIQUE"}
    dt = abs(float(ts_bbo) - float(ts_l2))
    if dt > tolerance_ms:
        return {"etat": INCOHERENT, "raison": "ECART_TEMPOREL", "dt_ms": round(dt, 6)}
    if abs(float(bbo_bid) - float(l2_bid_top)) > tolerance_prix or \
       abs(float(bbo_ask) - float(l2_ask_top)) > tolerance_prix:
        return {"etat": INCOHERENT, "raison": "SOMMET_L2_DIFFERE_BBO", "dt_ms": round(dt, 6)}
    return {"etat": COHERENT, "dt_ms": round(dt, 6)}


__all__ = ["verifier_coherence", "COHERENT", "INCOHERENT"]
