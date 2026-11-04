"""[COPY-VAULT pépite 285] LEADER EXECUTION EFFICIENCY : on compare les fills du leader au BBO/mid CAUSAL
disponible au même instant pour distinguer l'ALPHA (bon timing/direction) de la QUALITÉ D'EXÉCUTION (acheter
sous le mid, vendre au-dessus). Un leader qui gagne surtout par une exécution qu'on ne reproduira pas (maker
fin, placement) n'apporte pas le même edge copiable qu'un leader au vrai signal. Retour en bps signés (positif =
meilleur que le mid). Entrées invalides → UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def efficience(fill_prix: Any, mid_causal: Any, sens: str) -> dict[str, Any]:
    """ACHAT : amélioration = (mid - fill)/mid (positif si acheté sous le mid). VENTE : (fill - mid)/mid.
    Résultat en bps. mid ≤ 0, prix invalide ou sens inconnu → UNMEASURABLE (pas d'invention de qualité)."""
    if not (_fini(fill_prix) and _fini(mid_causal)) or mid_causal <= 0 or fill_prix <= 0:
        return {"efficience_bps": UNMEASURABLE, "raison": "PRIX_INVALIDE"}
    s = str(sens).upper()
    if s in ("ACHAT", "BUY", "LONG"):
        amelioration = (float(mid_causal) - float(fill_prix)) / float(mid_causal)
    elif s in ("VENTE", "SELL", "SHORT"):
        amelioration = (float(fill_prix) - float(mid_causal)) / float(mid_causal)
    else:
        return {"efficience_bps": UNMEASURABLE, "raison": "SENS_INCONNU"}
    return {"efficience_bps": round(amelioration * 10_000.0, 6),
            "meilleur_que_mid": amelioration > 0}


def execution_efficiency_receipt(*, fill_price: Any, causal_mid: Any, side: str) -> dict[str, Any]:
    """Bind execution efficiency to the observed causal mid, never to a later mark."""
    result = efficience(fill_price, causal_mid, side)
    if result.get("efficience_bps") == UNMEASURABLE:
        return {"status": UNMEASURABLE, **result}
    return {"status": "PROVEN", "efficiency_bps": result["efficience_bps"],
            "better_than_mid": bool(result["meilleur_que_mid"]), "causal_reference": True}


__all__ = ["efficience", "execution_efficiency_receipt", "UNMEASURABLE"]
