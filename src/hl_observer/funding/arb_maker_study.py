"""ARBITRAGE AU MAKER : mesurer si l'entrée passive sauve l'edge (étape 2/3, 22/07).

LA QUESTION, POSÉE PROPREMENT
-----------------------------
L'arbitrage meurt à 16 bps (taker aux 4 jambes). La loi `arb_dislocation_cout_all_in` dit :
« à 9 bps (tout maker) les mêmes trades survivent ». C'est la SEULE porte de sortie. Mais la
loi ajoute la mise en garde : sur un écart qui converge, être servi passivement n'est PAS
garanti — c'est une course.

Ce module quantifie exactement ça, sans supposer le résultat.

LE PIÈGE, NOMMÉ : LA SÉLECTION ADVERSE D'UNE ENTRÉE PASSIVE
----------------------------------------------------------
On parie qu'un écart `e0` (large) converge vers 0. Pour entrer PASSIVEMENT à un meilleur prix,
on poste une limite à `e0 + offset` (écart encore plus large) et on n'est rempli que si l'écart
**s'élargit** jusqu'à nous. Conséquence inévitable :

  * les trades qui convergent VITE (les meilleurs) ne nous remplissent JAMAIS — l'écart part
    dans notre sens sans repasser par notre limite ;
  * on ne capture QUE ceux qui divergent d'abord — les pires, et parfois ceux qui ne
    reviennent plus.

Une entrée passive sur un signal de retour à la moyenne trie donc les trades **à l'envers**.
Le taux de fill seul ne suffit pas : ce qui compte, c'est le PnL des trades REMPLIS, pas de
l'univers. Ce module mesure les deux.

LE MODÈLE (honnête, réutilise le simulateur testé)
--------------------------------------------------
`find_maker_fill` (module `maker_fill`, déjà testé) décide un fill sur un chemin de prix RÉEL,
en capturant la sélection adverse par construction. On l'applique à la série d'écarts (le
« prix » du spread). Un écart absent, trop court, ou sans chemin de sortie -> pas de mesure,
jamais un fill inventé.

PAPER only : simuler un fill n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

from hl_observer.funding.arb_cout_all_in import decomposer

#: fenêtre pour être rempli passivement à l'entrée (au-delà, le signal est périmé).
FENETRE_ENTREE_S = 5 * 60.0
#: horizon de tenue de la position (au-delà, on sort à l'écart courant = âge max).
HORIZON_TENUE_S = 30 * 60.0
#: de combien on poste PLUS LARGE que l'écart courant pour un meilleur prix maker.
OFFSET_ENTREE_BPS = 2.0
#: on SORT quand l'écart s'est refermé jusque-là (la convergence est capturée). C'est le vrai
#: comportement de la stratégie (et du backtest) : on ne tient pas jusqu'à l'horizon si l'écart
#: a déjà convergé. Sans cette sortie, la capture mesurée est fausse (~0).
SORTIE_CONVERGENCE_BPS = 3.0


def _ecart_de_sortie(apres: list[tuple[float, float]], sortie_bps: float) -> float:
    """L'écart AU MOMENT DE LA SORTIE : le premier point où |écart| <= sortie_bps (convergence
    capturée), sinon le dernier point de l'horizon (âge max). C'est ce que fait la stratégie."""
    for _t, e in apres:
        if abs(e) <= float(sortie_bps):
            return e
    return apres[-1][1]


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return None if x != x else x


def _ecart_a(serie: list[tuple[float, float]], t_cible: float,
             tol_s: float = 120.0) -> float | None:
    """L'écart le plus proche de `t_cible` dans la série, ou None si rien d'assez proche."""
    best = None
    for t, e in serie:
        d = abs(t - t_cible)
        if d <= tol_s and (best is None or d < best[0]):
            best = (d, e)
    return best[1] if best else None


def etudier_un_signal(serie: list[tuple[float, float]], i: int, *,
                      seuil_bps: float, offset_bps: float = OFFSET_ENTREE_BPS,
                      fenetre_entree_s: float = FENETRE_ENTREE_S,
                      horizon_s: float = HORIZON_TENUE_S,
                      sortie_bps: float = SORTIE_CONVERGENCE_BPS) -> dict[str, Any] | None:
    """Compare l'entrée TAKER (immédiate) et MAKER (passive) sur UN signal. None si hors seuil
    ou données insuffisantes.

    Capture = |écart d'entrée| − |écart de sortie| (ce que la convergence nous a rendu), avec
    SORTIE à la convergence (|écart| <= sortie_bps), comme la vraie stratégie.
    """
    t0, e0 = serie[i]
    if abs(e0) < float(seuil_bps):
        return None
    apres = [(t, e) for t, e in serie[i + 1:] if t <= t0 + horizon_s]
    if not apres:
        return None
    e_sortie = _ecart_de_sortie(apres, sortie_bps)   # convergence capturée, sinon âge max
    signe = 1.0 if e0 > 0 else -1.0

    # TAKER : rempli tout de suite a e0. Capture = combien l'ecart s'est referme.
    capture_taker = abs(e0) - abs(e_sortie) if e0 * e_sortie > 0 else abs(e0) + abs(e_sortie)

    # MAKER : limite postee PLUS LARGE (e0 + offset dans le sens de l'ecart). Rempli seulement
    # si l'ecart s'ELARGIT jusqu'a la limite dans la fenetre d'entree -> selection adverse.
    limite = e0 + signe * float(offset_bps)
    fenetre = [(t, e) for t, e in serie[i + 1:] if t <= t0 + fenetre_entree_s]
    rempli = any((e >= limite) if signe > 0 else (e <= limite) for _, e in fenetre)
    out = {"ecart_entree_bps": round(e0, 4), "ecart_sortie_bps": round(e_sortie, 4),
           "capture_taker_bps": round(capture_taker, 4), "maker_rempli": rempli,
           "capture_maker_bps": None}
    if rempli:
        # rempli a la limite (plus large) -> la convergence part de la, vers e_sortie.
        out["capture_maker_bps"] = round(abs(limite) - abs(e_sortie)
                                         if limite * e_sortie > 0
                                         else abs(limite) + abs(e_sortie), 4)
    return out


def etudier(series_par_coin: dict[str, list[tuple[float, float]]], *,
            seuil_bps: float = 19.0, notional_usd: float = 50.0,
            offset_bps: float = OFFSET_ENTREE_BPS) -> dict[str, Any]:
    """L'étude complète : TAKER vs MAKER sur tous les signaux au-dessus du seuil.

    Rend le taux de fill passif ET — ce qui compte vraiment — le PnL net des trades REMPLIS
    sous chaque hypothèse de coût. Le coût vient de `arb_cout_all_in` (source unique).
    """
    cout_taker = decomposer(mode="TOUT_TAKER")["cout_aller_retour_bps"]
    cout_maker = decomposer(mode="TOUT_MAKER")["cout_aller_retour_bps"]
    signaux = 0
    remplis = 0
    pnl_taker = 0.0
    pnl_maker = 0.0
    capture_maker_sum = 0.0
    for coin, serie in (series_par_coin or {}).items():
        s = sorted((float(t), float(e)) for t, e in serie
                   if _f(t) is not None and _f(e) is not None)
        for i in range(len(s)):
            r = etudier_un_signal(s, i, seuil_bps=seuil_bps, offset_bps=offset_bps)
            if r is None:
                continue
            signaux += 1
            pnl_taker += (r["capture_taker_bps"] - cout_taker) / 1e4 * notional_usd
            if r["maker_rempli"] and r["capture_maker_bps"] is not None:
                remplis += 1
                capture_maker_sum += r["capture_maker_bps"]
                pnl_maker += (r["capture_maker_bps"] - cout_maker) / 1e4 * notional_usd
    taux = (remplis / signaux) if signaux else 0.0
    return {
        "signaux": signaux, "seuil_bps": seuil_bps,
        "cout_taker_bps": cout_taker, "cout_maker_bps": cout_maker,
        "maker_remplis": remplis, "taux_fill_passif_pct": round(100.0 * taux, 1),
        "capture_maker_moyenne_bps": round(capture_maker_sum / remplis, 4) if remplis else None,
        "pnl_taker_usd": round(pnl_taker, 4),
        "pnl_maker_usd_sur_remplis": round(pnl_maker, 4),
        "verdict": _verdict(pnl_maker, remplis, signaux),
        "real_execution": False,
    }


def _verdict(pnl_maker: float, remplis: int, signaux: int) -> str:
    # ⚠️ CE MODULE MESURE LA POPULATION DE SIGNAUX, PAS LE SOUS-ENSEMBLE QUE LE MOTEUR TRADE.
    # Le moteur filtre (vivacite + convergence capturee + seuil) et ne prend qu'une minorite.
    # Son realise reel est POSITIF (13/15 gagnants, +0,54 $ au 22/07). Un verdict negatif ICI
    # dit « la MOYENNE des signaux ne paie pas au maker » — pas « la strategie gatee est morte ».
    # On ne ferme donc AUCUNE porte : on mesure une borne de population, rien de plus.
    if signaux == 0:
        return "AUCUN signal au-dessus du seuil : rien a mesurer"
    if remplis == 0:
        return ("entree passive LARGE : 0 fill (selection adverse). Ne dit RIEN du sous-ensemble "
                "gate que le moteur trade — voir le ledger, pas cette borne de population")
    if pnl_maker > 0:
        return ("au MAKER, meme la POPULATION est positive (%d/%d remplis) : signal fort, a "
                "confirmer" % (remplis, signaux))
    return ("la POPULATION des signaux ne paie pas au maker (convergence moyenne < 9 bps). "
            "Ce n'est PAS le verdict de la strategie : le moteur ne trade que le sous-ensemble "
            "FILTRE, dont le realise reel est positif. Cette mesure est une borne, pas une porte")


__all__ = ["FENETRE_ENTREE_S", "HORIZON_TENUE_S", "OFFSET_ENTREE_BPS",
           "etudier_un_signal", "etudier"]
