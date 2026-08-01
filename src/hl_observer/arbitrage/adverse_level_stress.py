"""[ARB pépites 238-239] ADVERSE-LEVEL STRESS (one/two-level) : AVANT l'entrée, simuler immédiatement ce qui arrive
si chaque jambe doit consommer UN niveau supplémentaire du carnet (238), ou DEUX (239, marchés plus fins). Un edge
qui ne survit pas à un ou deux niveaux adverses est trop fragile. On recalcule le VWAP d'exécution en descendant de
`niveaux` crans et on renvoie l'edge stressé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _vwap_apres(niveaux: Sequence[Any], quantite: float, saut: int) -> Any:
    """VWAP pour absorber `quantite` en commençant `saut` niveaux plus loin (adverse). Carnet insuffisant → None."""
    dispo = list(niveaux)[saut:]
    reste, notional = float(quantite), 0.0
    for niv in dispo:
        try:
            prix, taille = float(niv[0]), float(niv[1])
        except (TypeError, ValueError, IndexError):
            return None
        pris = min(reste, taille)
        notional += pris * prix
        reste -= pris
        if reste <= 1e-12:
            return notional / float(quantite)
    return None


def stresser(niveaux: Sequence[Any], quantite: Any, *, niveaux_adverses: int = 1,
             edge_base_bps: Any = None) -> dict[str, Any]:
    """Recalcule le VWAP en sautant `niveaux_adverses` crans et estime la dégradation d'edge. Carnet insuffisant
    après saut → UNMEASURABLE (on ne suppose pas que ça remplit). Un edge qui devient négatif est signalé fragile."""
    if not isinstance(quantite, (int, float)) or float(quantite) <= 0:
        return {"vwap_stresse": UNMEASURABLE, "raison": "QUANTITE_INVALIDE"}
    base = _vwap_apres(niveaux, float(quantite), 0)
    stresse = _vwap_apres(niveaux, float(quantite), int(niveaux_adverses))
    if base is None or stresse is None:
        return {"vwap_stresse": UNMEASURABLE, "raison": "CARNET_INSUFFISANT_APRES_STRESS"}
    degr_bps = (stresse - base) / base * 1e4          # >0 = on paie plus cher (achat)
    survit = None
    if isinstance(edge_base_bps, (int, float)):
        survit = (float(edge_base_bps) - abs(degr_bps)) > 0
    return {"vwap_base": round(base, 10), "vwap_stresse": round(stresse, 10),
            "degradation_bps": round(abs(degr_bps), 4), "niveaux_adverses": int(niveaux_adverses),
            "edge_survit": survit}


__all__ = ["stresser", "UNMEASURABLE"]
