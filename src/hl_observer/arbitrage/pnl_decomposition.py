"""[ARB #50] PnL DECOMPOSITION : décomposer le PnL net d'un épisode en cascade explicite —
gross dislocation → slippage jambe A → slippage jambe B → frais → perte de conversion → perte résiduelle → NET.
Chaque poste est visible ; le net n'est pas un chiffre opaque. Un poste MANQUANT rend le net UNMEASURABLE (on ne
comble jamais un coût inconnu par 0, ce qui gonflerait le net). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"

_POSTES_COUT = ("slippage_a_bps", "slippage_b_bps", "frais_bps", "conversion_bps", "residuel_bps")


def decomposer(*, gross_bps: Any, slippage_a_bps: Any, slippage_b_bps: Any, frais_bps: Any,
               conversion_bps: Any, residuel_bps: Any) -> dict[str, Any]:
    """net = gross − (slip_a + slip_b + frais + conversion + résiduel), tout en bps. Chaque poste (y compris
    gross) doit être fourni ; sinon net = UNMEASURABLE. Retourne aussi la cascade poste par poste."""
    valeurs = {"gross_bps": gross_bps, "slippage_a_bps": slippage_a_bps, "slippage_b_bps": slippage_b_bps,
               "frais_bps": frais_bps, "conversion_bps": conversion_bps, "residuel_bps": residuel_bps}
    manquants = [k for k, v in valeurs.items() if not isinstance(v, (int, float))]
    if manquants:
        return {"net_bps": UNMEASURABLE, "manquants": manquants, "raison": "POSTE_MANQUANT_NET_NON_CHIFFRABLE"}
    cout_total = sum(float(valeurs[k]) for k in _POSTES_COUT)
    net = float(gross_bps) - cout_total
    # cascade : point de départ = gross, puis on soustrait chaque coût
    reste = float(gross_bps)
    cascade = [{"poste": "gross_bps", "valeur_bps": round(float(gross_bps), 4), "cumul_bps": round(reste, 4)}]
    for k in _POSTES_COUT:
        reste -= float(valeurs[k])
        cascade.append({"poste": k, "valeur_bps": round(-float(valeurs[k]), 4), "cumul_bps": round(reste, 4)})
    return {"net_bps": round(net, 4), "cout_total_bps": round(cout_total, 4), "cascade": cascade}


__all__ = ["decomposer", "UNMEASURABLE"]
