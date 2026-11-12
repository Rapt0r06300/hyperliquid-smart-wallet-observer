"""ALPHA P19 — DYNAMIC PRICE DISCOVERY : qui mène le prix ? cross-corrélation + lead-lag asynchrone → venue_leader_score.

Pour deux venues, on mesure la corrélation croisée des rendements à différents lags : un pic à lag>0 signifie
que la venue A précède la venue B. On agrège en un `venue_leader_score` par venue (à quel point elle mène).
Information Share / Hayashi-Yoshida sont branchables plus tard ; ici la version cross-corr, robuste et testable.
Pur, 0 réseau, 0 ordre réel.

[S1.6, 2026-11-12] La seconde couche de ce module (en bas) branche justement Hayashi-Yoshida, pour
mesurer un décalage en MILLISECONDES sur des séries asynchrones — voir son propre en-tête.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def crosscorr_lead(ret_a: Sequence[float], ret_b: Sequence[float], *, max_lag: int = 5) -> dict[str, Any]:
    """corr(ret_a[t], ret_b[t+k]). Pic à k>0 ⇒ A précède B (A mène)."""
    n = min(len(ret_a), len(ret_b))
    corr: dict[int, float | None] = {}
    for k in range(-max_lag, max_lag + 1):
        xs, ys = [], []
        for t in range(n):
            if 0 <= t + k < n:
                xs.append(ret_a[t]); ys.append(ret_b[t + k])
        corr[k] = _pearson(xs, ys)
    valides = {k: v for k, v in corr.items() if v is not None}
    peak = max(valides, key=lambda k: valides[k]) if valides else None
    return {"corr_par_lag": corr, "peak_lag": peak, "a_mene": (peak is not None and peak > 0)}


def venue_leader_score(rendements_par_venue: Mapping[str, Sequence[float]], *, max_lag: int = 5) -> dict[str, float]:
    """Pour chaque paire de venues, qui mène ; score par venue = fraction des paires où elle mène."""
    venues = list(rendements_par_venue)
    gagne: dict[str, int] = {v: 0 for v in venues}
    total: dict[str, int] = {v: 0 for v in venues}
    for i in range(len(venues)):
        for j in range(i + 1, len(venues)):
            a, b = venues[i], venues[j]
            r = crosscorr_lead(rendements_par_venue[a], rendements_par_venue[b], max_lag=max_lag)
            if r["peak_lag"] is None:
                continue
            total[a] += 1; total[b] += 1
            if r["peak_lag"] > 0:
                gagne[a] += 1
            elif r["peak_lag"] < 0:
                gagne[b] += 1
    return {v: round(gagne[v] / total[v], 4) if total[v] else 0.0 for v in venues}


# ----------------------------------------------------------------------------------------------------
# S1.6 / GIS1-GIS5 — DECALAGE EN MILLISECONDES sur series ASYNCHRONES (Hayashi-Yoshida)
# ----------------------------------------------------------------------------------------------------
# POURQUOI cette seconde couche. `crosscorr_lead` ci-dessus travaille sur des lags ENTIERS de barres
# deja alignees : il ne peut pas exprimer « Binance mene Hyperliquid de 700 ms ». Or c'est precisement
# ce que dit la recherche du 12/11 (29/29 actifs, ~700 ms = deux blocs HyperBFT), et elle l'obtient avec
# l'estimateur de Hayashi-Yoshida, concu pour des series echangees a des instants IRREGULIERS et NON
# SYNCHRONISES — le cas des trades. HY ne reechantillonne PAS (reechantillonner fabrique du biais quand
# les deux series n'ont pas la meme cadence) : il somme les produits de rendements dont les INTERVALLES
# SE CHEVAUCHENT.
#
# GARDE-FOU CENTRAL. La source avertit qu'un « lead de 700 ms » est TRIVIAL a fabriquer par derive
# d'horloge, donnee perimee ou mauvais alignement de barres. Un decalage mesure sans ce controle ne vaut
# rien. `decalage_optimal` rend donc un VERDICT, pas seulement un nombre, et refuse de conclure quand le
# pic n'est pas distinct, qu'il touche le bord du balayage, ou qu'il derive entre sous-fenetres.

#: Pas et borne du balayage (methode sourcee : -2000 ms a +2000 ms par pas de 100 ms).
PAS_MS_DEFAUT = 100
BORNE_MS_DEFAUT = 2000
#: En dessous, on ne conclut pas : une correlation sur une poignee de rendements ne veut rien dire.
MIN_RENDEMENTS = 20
#: Plancher absolu : un pic qui ne depasse pas la mediane de ca n'est de toute facon rien.
MARGE_PIC_MINIMALE = 0.05
#: Le vrai critere : le pic doit se detacher de la DISPERSION de la courbe, pas d'une constante.
#: Un seuil absolu se trompe toujours — sur 41 decalages, du bruit produit facilement +0,12 d'ecart.
#: Calibre le 12/11 sur des cas construits : vrai lead = 11,7 a 20,7 ecarts-MAD ; bruit = 1,0 a 2,5.
#: 6 tombe au milieu du fosse, donc le seuil n'est pas ajuste au bord d'un cas particulier.
FACTEUR_DISPERSION_MINIMAL = 6.0
#: Derive maximale toleree du decalage entre la premiere et la seconde moitie de l'echantillon.
DERIVE_MAX_MS = 500
#: Tolerance (en correlation) pour considerer qu'un decalage appartient au PLATEAU du pic.
#: La correlation HY ne resout pas un decalage plus fin que l'intervalle entre deux ticks : autour du
#: vrai decalage, une PLAGE de valeurs est quasi equivalente. Prendre l'argmax brut revient a choisir
#: arbitrairement le PREMIER point de ce plateau (biais vers le bas, mesure le 12/11 : 100 ms annonces
#: pour un vrai decalage de 300 ms). On rend donc le CENTRE du plateau, et un plateau qui touche le
#: bord du balayage declenche le refus « BORD_DU_BALAYAGE ».
TOLERANCE_PLATEAU = 0.01

VERDICT_MESURE = "MESURE"
VERDICT_SIGNAL_INSUFFISANT = "SIGNAL_INSUFFISANT"
VERDICT_PIC_NON_DISTINCT = "PIC_NON_DISTINCT"
VERDICT_BORD_DU_BALAYAGE = "BORD_DU_BALAYAGE"
VERDICT_ARTEFACT_HORLOGE = "ARTEFACT_HORLOGE_SUSPECTE"


def rendements_horodates(ticks: Sequence[tuple[int, float]]) -> list[tuple[int, int, float]]:
    """(debut_ms, fin_ms, rendement) a partir de ticks ``(ts_ms, prix)``.

    Les prix <= 0 et les horodatages non strictement croissants sont ecartes : un prix nul ou une
    horloge qui recule ne sont pas des observations exploitables.
    """
    propres: list[tuple[int, float]] = []
    for item in ticks or ():
        try:
            ts, prix = int(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if prix <= 0.0:
            continue
        if propres and ts <= propres[-1][0]:
            continue
        propres.append((ts, prix))
    return [(ts0, ts1, math.log(p1 / p0))
            for (ts0, p0), (ts1, p1) in zip(propres, propres[1:])]


def hayashi_yoshida(a: Sequence[tuple[int, int, float]], b: Sequence[tuple[int, int, float]],
                    *, decalage_ms: int = 0) -> tuple[float | None, int]:
    """(correlation HY, nombre de paires chevauchantes) pour l'hypothese « ``a`` precede ``b`` de
    ``decalage_ms`` millisecondes ».

    CONVENTION DE SIGNE (une erreur ici inverserait la conclusion, donc elle est explicite et testee) :
    si ``a`` mene, les mouvements de ``b`` arrivent PLUS TARD. Pour les confronter, on ramene donc les
    intervalles de ``b`` EN ARRIERE de ``decalage_ms``. Un ``decalage_ms`` POSITIF teste ainsi
    « ``a`` mene de d ms » ; un pic a d > 0 signifie que ``a`` precede, un pic a d < 0 que ``b`` precede.

    O(n_a + n_b) par decalage : les deux series sont triees et les intervalles d'une meme serie ne se
    chevauchent pas.
    """
    if not a or not b:
        return None, 0
    var_a = sum(r * r for _s, _e, r in a)
    var_b = sum(r * r for _s, _e, r in b)
    if var_a <= 0.0 or var_b <= 0.0:
        return None, 0
    cov = 0.0
    paires = 0
    j = 0
    d = int(decalage_ms)
    for debut_a, fin_a, r_a in a:
        while j < len(b) and (b[j][1] - d) <= debut_a:
            j += 1
        k = j
        while k < len(b) and (b[k][0] - d) < fin_a:
            cov += r_a * b[k][2]
            paires += 1
            k += 1
    return cov / math.sqrt(var_a * var_b), paires


def _mediane(valeurs: Sequence[float]) -> float:
    ordonnees = sorted(valeurs)
    n = len(ordonnees)
    if n == 0:
        return 0.0
    milieu = n // 2
    return ordonnees[milieu] if n % 2 else (ordonnees[milieu - 1] + ordonnees[milieu]) / 2.0


def decalage_optimal(ticks_a: Sequence[tuple[int, float]], ticks_b: Sequence[tuple[int, float]],
                     *, nom_a: str = "A", nom_b: str = "B", pas_ms: int = PAS_MS_DEFAUT,
                     borne_ms: int = BORNE_MS_DEFAUT,
                     controler_la_derive: bool = True) -> dict[str, Any]:
    """Qui mene, et de combien de MILLISECONDES — avec un verdict honnete.

    Balaye le decalage de ``-borne_ms`` a ``+borne_ms`` par pas de ``pas_ms`` et prend l'argmax de la
    correlation de Hayashi-Yoshida, puis REFUSE de conclure si :

    * trop peu de rendements (``SIGNAL_INSUFFISANT``) ;
    * le pic ne depasse pas nettement la mediane de la courbe (``PIC_NON_DISTINCT``) : une courbe plate
      signifie qu'aucune precedence n'est lisible, pas qu'elle vaut zero ;
    * le pic touche le bord du balayage (``BORD_DU_BALAYAGE``) : le vrai decalage est peut-etre dehors ;
    * le decalage de la premiere moitie de l'echantillon s'ecarte de plus de ``DERIVE_MAX_MS`` de celui
      de la seconde (``ARTEFACT_HORLOGE_SUSPECTE``) — le faux positif contre lequel la source alerte.
    """
    ra = rendements_horodates(ticks_a)
    rb = rendements_horodates(ticks_b)
    pas = max(1, int(pas_ms))
    borne = max(pas, int(borne_ms))

    if len(ra) < MIN_RENDEMENTS or len(rb) < MIN_RENDEMENTS:
        return {"verdict": VERDICT_SIGNAL_INSUFFISANT, "decalage_ms": None, "qui_mene": None,
                "correlation": None, "courbe": {}, "rendements": (len(ra), len(rb)),
                "raison": f"{len(ra)} et {len(rb)} rendements ; il en faut {MIN_RENDEMENTS} de chaque"}

    courbe: dict[int, float] = {}
    paires_max = 0
    for d in range(-borne, borne + 1, pas):
        corr, paires = hayashi_yoshida(ra, rb, decalage_ms=d)
        if corr is not None:
            courbe[d] = corr
            paires_max = max(paires_max, paires)
    if not courbe:
        return {"verdict": VERDICT_SIGNAL_INSUFFISANT, "decalage_ms": None, "qui_mene": None,
                "correlation": None, "courbe": {}, "rendements": (len(ra), len(rb)),
                "raison": "aucun chevauchement entre les deux series"}

    brut = max(courbe, key=lambda d: courbe[d])
    valeur = courbe[brut]
    plateau = sorted(d for d, v in courbe.items() if v >= valeur - TOLERANCE_PLATEAU)
    pic = plateau[len(plateau) // 2] if plateau else brut      # centre du plateau, pas son premier point
    base = {"courbe": courbe, "decalage_ms": pic, "correlation": round(valeur, 6),
            "plateau_ms": (plateau[0], plateau[-1]) if plateau else None,
            "rendements": (len(ra), len(rb)), "paires_chevauchantes": paires_max,
            "qui_mene": (nom_a if pic > 0 else nom_b if pic < 0 else None)}

    valeurs = list(courbe.values())
    mediane = _mediane(valeurs)
    ecart = valeur - mediane
    dispersion = _mediane([abs(v - mediane) for v in valeurs])        # MAD, robuste aux extremes
    seuil = max(MARGE_PIC_MINIMALE, FACTEUR_DISPERSION_MINIMAL * dispersion)
    base_stats = {"ecart_au_median": round(ecart, 6), "dispersion": round(dispersion, 6),
                  "ecarts_de_dispersion": round(ecart / dispersion, 2) if dispersion > 0 else None}
    if ecart < seuil:
        return {**base, **base_stats, "verdict": VERDICT_PIC_NON_DISTINCT, "qui_mene": None,
                "raison": f"courbe plate : le pic ne depasse la mediane que de {ecart:.3f} pour une "
                          f"dispersion de {dispersion:.3f} — aucune precedence lisible"}

    if plateau and (plateau[0] <= -borne or plateau[-1] >= borne):
        return {**base, **base_stats, "verdict": VERDICT_BORD_DU_BALAYAGE,
                "raison": f"le plateau du pic touche le bord du balayage (+-{borne} ms) : le vrai "
                          f"decalage est probablement DEHORS, elargir avant de conclure"}

    if controler_la_derive:
        mi_a, mi_b = len(ticks_a) // 2, len(ticks_b) // 2
        if mi_a > MIN_RENDEMENTS and mi_b > MIN_RENDEMENTS:
            moities = [
                decalage_optimal(ticks_a[:mi_a], ticks_b[:mi_b], pas_ms=pas, borne_ms=borne,
                                 controler_la_derive=False),
                decalage_optimal(ticks_a[mi_a:], ticks_b[mi_b:], pas_ms=pas, borne_ms=borne,
                                 controler_la_derive=False),
            ]
            mesures = [m["decalage_ms"] for m in moities if m["verdict"] == VERDICT_MESURE]
            if len(mesures) == 2 and abs(mesures[0] - mesures[1]) > DERIVE_MAX_MS:
                return {**base, **base_stats, "verdict": VERDICT_ARTEFACT_HORLOGE,
                        "qui_mene": None,
                        "derive_ms": (mesures[0], mesures[1]),
                        "raison": f"decalage {mesures[0]} ms sur la 1re moitie contre {mesures[1]} ms sur "
                                  f"la 2e : derive d'horloge probable, pas une precedence de marche"}

    return {**base, **base_stats, "verdict": VERDICT_MESURE,
            "raison": f"{base['qui_mene']} precede de {abs(pic)} ms (correlation {valeur:.3f})"}


__all__ = ["crosscorr_lead", "venue_leader_score",
           # S1.6 — decalage en millisecondes sur series asynchrones
           "PAS_MS_DEFAUT", "BORNE_MS_DEFAUT", "MIN_RENDEMENTS", "MARGE_PIC_MINIMALE", "FACTEUR_DISPERSION_MINIMAL", "DERIVE_MAX_MS", "TOLERANCE_PLATEAU",
           "VERDICT_MESURE", "VERDICT_SIGNAL_INSUFFISANT", "VERDICT_PIC_NON_DISTINCT",
           "VERDICT_BORD_DU_BALAYAGE", "VERDICT_ARTEFACT_HORLOGE",
           "rendements_horodates", "hayashi_yoshida", "decalage_optimal"]
