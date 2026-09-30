"""[COPY-VAULT pépite 281] SOURCE EXECUTION-STYLE PROFILE : pour chaque vault, le taux maker/taker, la part de
partial fills et le type de sizing deviennent des CARACTÉRISTIQUES DE COPYABILITÉ. On ne juge pas un leader
seulement à son PnL : on décrit COMMENT il exécute, car c'est ce qui détermine si on peut le répliquer. Aucun
fill exploitable → profil UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.copy_vault.source_maker_taker_classifier import classer, MAKER, TAKER

UNMEASURABLE = "UNMEASURABLE"


def profiler(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrège les fills en profil : taux_maker, taux_taker (sur les fills classifiables), part_partial, n.
    Les fills non classifiables sont comptés à part (ni maker ni taker) et n'inventent pas de rôle."""
    if not fills:
        return {"profil": UNMEASURABLE, "raison": "AUCUN_FILL"}
    n = len(fills)
    n_maker = n_taker = n_indetermine = n_partial = 0
    for f in fills:
        c = classer(f).get("classe")
        if c == MAKER:
            n_maker += 1
        elif c == TAKER:
            n_taker += 1
        else:
            n_indetermine += 1
        if f.get("partial") is True or f.get("partiel") is True:
            n_partial += 1
    classifies = n_maker + n_taker
    return {
        "n": n,
        "taux_maker": round(n_maker / classifies, 6) if classifies else UNMEASURABLE,
        "taux_taker": round(n_taker / classifies, 6) if classifies else UNMEASURABLE,
        "n_indetermine": n_indetermine,
        "part_partial": round(n_partial / n, 6),
    }


__all__ = ["profiler", "UNMEASURABLE"]
