"""[ALL pépite 246] SAME-DIRECTION INTENT AGGREGATION : plusieurs modules voulant ACHETER simultanément le même coin
peuvent partager UNE intention agrégée si l'économie est meilleure (un seul gros ordre paie moins de spread/frais
fixes que N petits). On agrège les intentions de même sens par (venue, coin) et on garde la trace des contributions
pour l'attribution ultérieure (#247). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_TOL = 1e-12


def agreger(intentions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Agrège par (venue, coin, sens) les intentions de MÊME direction en un ordre unique par groupe, en
    conservant la liste des contributions (module → montant). Sens déduit du signe du montant."""
    groupes: dict[tuple, dict[str, Any]] = {}
    for it in intentions:
        m = it.get("montant_signe")
        coin, venue = it.get("coin"), it.get("venue")
        if not isinstance(m, (int, float)) or abs(float(m)) <= _TOL or not coin or not venue:
            continue
        sens = "ACHAT" if float(m) > 0 else "VENTE"
        cle = (str(venue).upper(), str(coin).upper(), sens)
        g = groupes.setdefault(cle, {"total": 0.0, "contributions": []})
        g["total"] = round(g["total"] + float(m), 8)
        g["contributions"].append({"module": it.get("module"), "montant": float(m)})
    out = [{"venue": k[0], "coin": k[1], "sens": k[2], "montant_agrege": v["total"],
            "contributions": v["contributions"], "n": len(v["contributions"])}
           for k, v in groupes.items()]
    return {"ordres_agreges": out, "n_groupes": len(out)}


__all__ = ["agreger"]
