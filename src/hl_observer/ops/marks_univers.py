"""MARQUER TOUT L'UNIVERS, PAS SEULEMENT LA SHORTLIST (21/07).

LE CONSTAT
----------
« Ce chiffre ne grandit jamais » — le total de marks consolidés (~384 000) bouge de +137
entre deux lancements espacés de 5 min. Mesure : le pool **croît réellement** (+28 676 sur la
journée, ~1 240 marks/h, pool frais, zéro doublon) mais **0,43 %/h sur une base de 384 k est
invisible à l'œil**.

La cause profonde du débit : le runtime n'écrit des marks que pour la **shortlist viable** —
mesuré ce soir, **6 coins**. Le scanner, lui, récupère déjà le prix perp (`markPx`) de **tout
l'univers perp∩spot** (~100-200 coins) à chaque passe, puis le jette pour tous les coins non
viables. On paie l'appel réseau, on calcule le prix, et on n'en garde presque rien.

CE QUE FAIT CE MODULE
---------------------
Il transforme un instantané `{coin: mid}` — celui que le scanner a DÉJÀ en main — en lignes de
marks. Aucun appel réseau nouveau, aucun prix inventé : on ne fait qu'arrêter de jeter des
prix réels que l'on vient de mesurer.

Effet attendu : la largeur de l'univers marqué passe de ~6 à ~100-200 coins par passe. Le
total croît plus vite, mais surtout il **couvre bien plus de coins** — ce qui sert directement
le markout copy (un leader trade des coins bien au-delà de la shortlist carry ; c'est ce qui
laissait 1 047 fills sans prix « PAS_DE_MARK_AU_FILL » encore ce soir).

CE QUE ÇA N'EST PAS
-------------------
Plus de marks n'est PAS plus de PnL. C'est plus de **mesure** : une meilleure couverture du
markout, un replay plus riche. On ne promet rien d'autre, et on n'invente aucun prix — un mid
absent, nul ou non fini est **ignoré**, jamais comblé.

Règle dure conservée : un prix doit être FRAIS. Ce module écrit l'instantané au moment où le
scanner l'a mesuré ; il ne réécrit jamais un vieux prix avec un horodatage neuf (ce serait
fabriquer de l'immobilité, aussi mensonger que fabriquer un mouvement).

PAPER only : enregistrer un prix observé n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

#: bornes de plausibilité d'un mid. Hors de là, ce n'est pas un prix, c'est une anomalie
#: (0, négatif, inf, NaN, ou une valeur grotesque issue d'une mauvaise paire).
MID_MIN = 1e-12
MID_MAX = 1e12


def _mid(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x if MID_MIN <= x <= MID_MAX else None


def lignes_marks(mids: dict[str, Any], *, ts_s: float) -> list[dict[str, Any]]:
    """`{coin: mid}` -> `[{coin, ts, mid}]`, prix invalides ÉCARTÉS (jamais comblés).

    Dédup intra-lot sur le coin : deux entrées pour le même coin dans un même instantané
    seraient une incohérence de source, on garde la première vue.
    """
    t = _mid(ts_s)
    if t is None or t <= 0:
        return []
    out: list[dict[str, Any]] = []
    vus: set[str] = set()
    for coin, mid in (mids or {}).items():
        c = str(coin or "").strip().upper()
        if not c or c in vus:
            continue
        m = _mid(mid)
        if m is None or m <= 0:
            continue
        vus.add(c)
        out.append({"coin": c, "ts": float(t), "mid": m})
    return out


def enregistrer_univers(root: str, mids: dict[str, Any], *, ts_s: float) -> int:
    """Écrit un mark par coin de `mids` dans le flux replay. Retourne le nombre écrit.

    S'appuie sur l'écrivain firehose existant (append atomique, cap par fichier) : on ne
    duplique pas la mécanique d'écriture, on lui donne juste un univers plus large.
    **Ne lève jamais** — un enregistreur qui casse le scanner serait pire que l'absence.
    """
    try:
        lignes = lignes_marks(mids, ts_s=ts_s)
        if not lignes:
            return 0
        from hl_observer.ops.decision_firehose import enregistrer_marks
        # enregistrer_marks reconstruit {coin: mid} et applique déjà ses propres garde-fous ;
        # on lui passe l'univers complet au lieu de la seule shortlist.
        return enregistrer_marks(root, {l["coin"]: l["mid"] for l in lignes}, ts_s=ts_s)
    except Exception:  # noqa: BLE001
        return 0


__all__ = ["MID_MIN", "MID_MAX", "lignes_marks", "enregistrer_univers"]
