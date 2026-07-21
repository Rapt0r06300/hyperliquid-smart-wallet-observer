"""COMBIEN DE TEMPS UN COIN SORT-IL DU PLANCHER ? (idée #7, 21/07)

LE CONSTAT
----------
57 % de nos relevés de funding valent EXACTEMENT 0,125 bps/h. Ce n'est pas une coïncidence :
c'est la bande morte de la formule publique d'Hyperliquid
(`F = premium + clamp(0,125 − premium, ±5)`), qui colle tous les coins au plancher tant que
|premium| < ~5 bps.

Conséquence : quand tout le monde est au plancher, **classer les coins par funding ne classe
que du bruit**. C'est exactement ce qui a produit la corrélation −0,596 du 21/07 (le z-score
au plancher). Le seul signal qui reste est le COÛT (break-even), et on l'a corrigé.

Mais il existe un signal bien plus intéressant, qu'on ne mesurait pas :

    **quel coin SORT du plancher, à quelle fréquence, et pendant combien de temps ?**

Un coin qui passe 20 % de son temps à 0,5 bps/h rapporte 4× plus qu'un coin scotché au
plancher — et cette information n'apparaît dans aucun instantané. Elle ne vit que dans
l'historique, que notre journal de scans enregistre depuis le 21/07.

CE QUE CE MODULE FAIT — et pas plus
-----------------------------------
Il décrit un PASSÉ. Il ne prédit rien : `part_hors_plancher` n'est pas une probabilité de
sortir demain. C'est une statistique descriptive, utile pour choisir un univers de scan, pas
pour dimensionner une position. Le sizing reste gouverné par le rendement net mesuré.

PAPER only.
"""
from __future__ import annotations

from typing import Any, Iterable

from hl_observer.funding.funding_previsionnel import TAUX_INTERET_BPS_H

#: marge au-dessus du plancher : sous ça, on est dans le bruit d'arrondi, pas « hors plancher ».
MARGE_HORS_PLANCHER_BPS = 0.005
#: sous ce nombre d'observations, un pourcentage ne veut rien dire.
OBSERVATIONS_MIN = 24


def est_hors_plancher(funding_bps_h: Any, marge: float = MARGE_HORS_PLANCHER_BPS) -> bool:
    """Le funding dépasse-t-il vraiment le plancher protocolaire ?"""
    if isinstance(funding_bps_h, bool) or not isinstance(funding_bps_h, (int, float)):
        return False
    f = float(funding_bps_h)
    return f == f and f > TAUX_INTERET_BPS_H + float(marge)


def profil(lignes: Iterable[dict], *, marge: float = MARGE_HORS_PLANCHER_BPS) -> dict[str, Any]:
    """{coin: {observations, part_hors_plancher_pct, funding_moyen, funding_max,
    gain_relatif_vs_plancher}}. Un coin sous `OBSERVATIONS_MIN` est marqué `insuffisant`."""
    par_coin: dict[str, list[float]] = {}
    for l in lignes or ():
        if not isinstance(l, dict):
            continue
        c = str(l.get("coin") or "").upper()
        f = l.get("funding_bps_h")
        if not c or isinstance(f, bool) or not isinstance(f, (int, float)) or f != f:
            continue
        par_coin.setdefault(c, []).append(float(f))
    out: dict[str, Any] = {}
    for c, v in par_coin.items():
        n = len(v)
        hors = sum(1 for f in v if est_hors_plancher(f, marge))
        moy = sum(v) / n
        out[c] = {
            "observations": n,
            "insuffisant": n < OBSERVATIONS_MIN,
            "part_hors_plancher_pct": round(100.0 * hors / n, 2),
            "funding_moyen_bps_h": round(moy, 5),
            "funding_max_bps_h": round(max(v), 5),
            # ce que le coin rapporte comparé à un coin scotché au plancher : c'est LE nombre
            # qui justifierait de préférer un univers à un autre.
            "gain_relatif_vs_plancher": round(moy / TAUX_INTERET_BPS_H, 4)
            if TAUX_INTERET_BPS_H > 0 else None,
        }
    return out


def classement(lignes: Iterable[dict], **kw) -> list[tuple[str, float]]:
    """Les coins triés par temps passé hors du plancher, les insuffisants exclus (pas
    relégués : **exclus**, parce qu'un pourcentage sur 3 observations est une illusion)."""
    p = profil(lignes, **kw)
    return sorted(((c, d["part_hors_plancher_pct"]) for c, d in p.items()
                   if not d["insuffisant"]), key=lambda kv: -kv[1])


def resume(lignes: Iterable[dict], **kw) -> dict[str, Any]:
    """Vue d'ensemble, pour le rapport du matin."""
    p = profil(lignes, **kw)
    exploitables = {c: d for c, d in p.items() if not d["insuffisant"]}
    if not exploitables:
        return {"coins": len(p), "exploitables": 0, "vide": True,
                "detail": "aucun coin n'atteint %d observations — le journal de scans est "
                          "encore jeune (il en produit ~2 900/jour)" % OBSERVATIONS_MIN}
    total = sum(d["observations"] for d in exploitables.values())
    hors = sum(d["observations"] * d["part_hors_plancher_pct"] / 100.0
               for d in exploitables.values())
    cl = classement(lignes, **kw)
    return {
        "coins": len(p), "exploitables": len(exploitables), "vide": False,
        "part_globale_hors_plancher_pct": round(100.0 * hors / total, 2),
        "meilleur": cl[0][0] if cl else None,
        "classement": cl[:10],
        "note": "statistique DESCRIPTIVE d'un passé — jamais une probabilité de sortir demain",
    }


__all__ = ["MARGE_HORS_PLANCHER_BPS", "OBSERVATIONS_MIN", "est_hors_plancher", "profil",
           "classement", "resume"]
