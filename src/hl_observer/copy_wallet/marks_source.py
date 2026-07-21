"""LA SOURCE DES MARKS — pourquoi 97,6 % des fills n'avaient pas de prix (21/07).

LE DIAGNOSTIC
-------------
La whitelist copy était vide : 12 leaders évalués, 0 qualifiés, aucun n'atteignant les 30
mesures exigées. On a longtemps cru que la porte était trop stricte. Elle ne l'était pas — elle
n'avait **rien à juger**.

    fills bruts observés      7 184
    fills avec un markout       173   ->  **2,4 %**

Instrumentation de la jointure : **88,4 % des fills se perdaient sur « pas de mark »**. Puis
la mesure qui a tout expliqué :

    marks (lus par le pipeline) : de −319,1 h à **−10,9 h**   ← s'arrêtent il y a 11 h
    fills                        : de  −11,8 h à   −0,2 h    ← commencent il y a 11,8 h
                                                  1 h de recouvrement

Ce n'était ni la fenêtre, ni la densité : sur les coins que les leaders tradent, les marks
tombent toutes les **2 secondes** (BTC, HYPE, ETH). Le pipeline lisait `_merged/marks.jsonl`,
figé à 10:06, pendant que les shards bruts `marks.*.jsonl` continuaient d'être écrits jusqu'à
20:38. **La collecte vivait ; c'est la consolidation qui n'avait pas tourné depuis 11 heures.**

CE QUE CE MODULE CORRIGE
------------------------
1. **Il lit les shards FRAIS en plus du consolidé.** Dépendre d'une consolidation qui peut ne
   pas avoir tourné, c'est faire reposer une mesure sur une tâche de ménage.
2. **Il prend le mark le plus proche dans le temps, avant OU après.** L'ancienne règle ne
   regardait qu'après le fill (`ts <= t <= ts+300`) : un mark 30 s AVANT était rejeté, un mark
   290 s APRÈS était accepté. Une asymétrie qui n'a aucune justification — le meilleur estimé
   du mid à l'instant du fill est le mark le plus PROCHE, des deux côtés.
3. **Il retourne l'écart temporel** de chaque appariement, pour qu'un mark trop lointain reste
   contestable au lieu d'être noyé dans la moyenne.
4. **Il CRIE quand les fenêtres ne se recouvrent pas.** C'est ce qui manquait le plus : ce bug
   a survécu 11 heures parce que le pipeline produisait 173 lignes au lieu de 7 000 **sans
   rien dire**. Un pipeline qui perd 97 % de sa matière doit le déclarer.

PAPER only : dater un prix n'est pas passer un ordre.
"""
from __future__ import annotations

import bisect
from pathlib import Path
from typing import Any

#: au-delà, le mark n'est plus « le prix au moment du fill ». Choisi égal à la fenêtre
#: historique (300 s) pour que le correctif n'assouplisse RIEN : il corrige l'asymétrie
#: (avant OU après) sans élargir la tolérance.
TOLERANCE_FILL_S = 300.0
#: fenêtre autour de l'instant `fill + horizon` pour le prix forward.
TOLERANCE_FORWARD_S = 900.0
#: en deçà, le recouvrement marks/fills est considéré comme ROMPU et signalé.
RECOUVREMENT_MIN_FRAC = 0.5


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return None if x != x else x


def charger_marks(root: str | Path) -> dict[str, list[tuple[float, float]]]:
    """Les marks du consolidé **ET** des shards plus récents, dédupliqués et triés.

    Le consolidé peut avoir des heures de retard (mesuré : 11 h). Les shards, eux, sont écrits
    en continu. On lit les deux : c'est la seule façon de ne pas faire dépendre une mesure
    d'une tâche de ménage qui a pu ne pas tourner.
    """
    from hl_observer.backtesting.ab_flag_replay import load_jsonl, marks_by_coin
    from hl_observer.backtesting.recherche_scenario import repertoire_replay_consolide

    racine = Path(root)
    base = racine / "runtime" / "replay"
    rows: list[dict] = []
    consolide = repertoire_replay_consolide(racine) / "marks.jsonl"
    if consolide.exists():
        rows.extend(load_jsonl(str(consolide)))
    # les shards du jour : `marks.<pid>.jsonl` à la RACINE de runtime/replay
    for shard in sorted(base.glob("marks.*.jsonl")):
        try:
            rows.extend(load_jsonl(str(shard)))
        except OSError:
            continue
    par_coin = marks_by_coin(rows)
    return {c: sorted(set(pts)) for c, pts in par_coin.items()}


def mark_le_plus_proche(points: list[tuple[float, float]], cible: float,
                        tolerance_s: float) -> tuple[float, float] | None:
    """`(mid, ecart_s)` du mark le plus proche de `cible`, **avant ou après**, ou None.

    L'ancienne règle ne regardait qu'après : un mark 30 s AVANT le fill était rejeté quand un
    mark 290 s APRÈS était retenu. Rien ne justifie cette asymétrie — et elle coûtait la
    moitié des appariements possibles.
    """
    if not points:
        return None
    ts = [t for t, _ in points]
    i = bisect.bisect_left(ts, cible)
    best: tuple[float, float] | None = None
    for j in (i - 1, i):
        if 0 <= j < len(points):
            d = abs(points[j][0] - cible)
            if d <= float(tolerance_s) and (best is None or d < best[1]):
                best = (points[j][1], d)
    return best


def diagnostic_recouvrement(marks: dict[str, list[tuple[float, float]]],
                            fills_ts: list[float]) -> dict[str, Any]:
    """Les marks couvrent-ils la période des fills ? Le contrôle qui manquait.

    Ce bug a vécu 11 heures parce que le pipeline rendait 173 lignes au lieu de 7 000 **sans
    rien dire**. Une mesure qui perd 97 % de sa matière doit le déclarer, pas se contenter
    d'être petite.
    """
    tm = [t for pts in marks.values() for t, _ in pts]
    tf = [t for t in (fills_ts or ()) if _f(t) is not None]
    if not tm or not tf:
        return {"rompu": True, "motif": "marks ou fills absents",
                "marks_n": len(tm), "fills_n": len(tf)}
    m0, m1 = min(tm), max(tm)
    f0, f1 = min(tf), max(tf)
    debut, fin = max(m0, f0), min(m1, f1)
    chevauche = max(0.0, fin - debut)
    duree_fills = max(1e-9, f1 - f0)
    frac = chevauche / duree_fills
    retard_h = (f1 - m1) / 3600.0
    rompu = frac < RECOUVREMENT_MIN_FRAC
    return {
        "rompu": rompu,
        "recouvrement_frac": round(frac, 4),
        "recouvrement_h": round(chevauche / 3600.0, 2),
        "fills_etendue_h": round(duree_fills / 3600.0, 2),
        "marks_finissent_avant_les_fills_h": round(retard_h, 2),
        "marks_n": len(tm), "fills_n": len(tf),
        "motif": ("les marks s'arretent %.1f h AVANT le dernier fill : la consolidation "
                  "ou la collecte est en retard — la mesure de markout est structurellement "
                  "incomplete, ce n'est PAS un resultat" % retard_h) if rompu else "",
    }


def apparier(marks: dict[str, list[tuple[float, float]]], *, coin: str, ts: float,
             horizon_s: float, tolerance_fill_s: float = TOLERANCE_FILL_S,
             tolerance_forward_s: float = TOLERANCE_FORWARD_S) -> dict[str, Any] | None:
    """`{mid_at_fill, mid_forward, ecart_fill_s, ecart_forward_s}` ou None.

    None est retourné **avec une cause** via `apparier_avec_cause` ; ici on reste minimal pour
    les appelants qui n'ont besoin que du résultat.
    """
    r = apparier_avec_cause(marks, coin=coin, ts=ts, horizon_s=horizon_s,
                            tolerance_fill_s=tolerance_fill_s,
                            tolerance_forward_s=tolerance_forward_s)
    return r if r.get("ok") else None


def apparier_avec_cause(marks: dict[str, list[tuple[float, float]]], *, coin: str, ts: float,
                        horizon_s: float, tolerance_fill_s: float = TOLERANCE_FILL_S,
                        tolerance_forward_s: float = TOLERANCE_FORWARD_S) -> dict[str, Any]:
    """Comme `apparier`, mais dit TOUJOURS pourquoi ça n'a pas marché.

    Sans cause nommée, on ne peut pas distinguer « ce leader trade un coin exotique » de
    « notre consolidation est en retard » — et c'est précisément la confusion qui a coûté
    11 heures de mesure.
    """
    t = _f(ts)
    if t is None or t <= 0:
        return {"ok": False, "cause": "HORODATAGE_ABSENT"}
    pts = marks.get(str(coin or "").upper())
    if not pts:
        return {"ok": False, "cause": "COIN_SANS_MARK"}
    a = mark_le_plus_proche(pts, t, tolerance_fill_s)
    if a is None:
        return {"ok": False, "cause": "PAS_DE_MARK_AU_FILL"}
    b = mark_le_plus_proche(pts, t + float(horizon_s), tolerance_forward_s)
    if b is None:
        return {"ok": False, "cause": "PAS_DE_MARK_FORWARD"}
    return {"ok": True, "mid_at_fill": a[0], "mid_forward": b[0],
            "ecart_fill_s": round(a[1], 3), "ecart_forward_s": round(b[1], 3)}


__all__ = ["TOLERANCE_FILL_S", "TOLERANCE_FORWARD_S", "RECOUVREMENT_MIN_FRAC",
           "charger_marks", "mark_le_plus_proche", "diagnostic_recouvrement",
           "apparier", "apparier_avec_cause"]
