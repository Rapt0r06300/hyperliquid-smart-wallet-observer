"""ARBITRAGE AU PRIX EXÉCUTABLE — le +0,54 $ gaté survit-il aux vrais fills ? (Levier 3, 22/07).

LA VÉRITÉ GÊNANTE
-----------------
Le réalisé gaté (+0,54 $, 13/15) est mesuré au **MID**, et `collecter_dispersion_venues` admet
lui-même : « la couverture Binance est conceptuelle ». Or on ne TRADE pas au mid : on **franchit
le spread** (on paie l'ask en achetant, on encaisse le bid en vendant), sur les DEUX venues, à
l'ENTRÉE et à la SORTIE = 4 franchissements ; et à la taille réelle on **marche le carnet**
(impact). Un edge qui vit au mid peut mourir à l'exécution.

CE MODULE EST UN MODÈLE, PAS UNE MESURE — ET LE DIT
---------------------------------------------------
On n'a pas encore capturé le carnet (bid/ask + profondeur) ; tant qu'on ne l'a pas, tout chiffre
« exécutable » est MODÉLISÉ. On prend donc des hypothèses **conservatrices** (spread large plutôt
qu'optimiste) et on les rend explicites, pour ne jamais maquiller un mid-illusion en edge. La
vraie levée du doute = capturer le carnet (`ecart_prix_bps` existe déjà ; il manque bid/ask/taille) ;
c'est la prochaine brique de COLLECTE, notée ici noir sur blanc.

Règle : au prix exécutable, un signal ne survit que si la convergence capturée dépasse le coût
exécutable complet. Deny-by-default : spread inconnu -> hypothèse LARGE (le doute coûte cher, pas
gratuit). PAPER only : modéliser un coût n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any, Sequence

#: 4 jambes taker (2 venues × entrée/sortie), cohérent avec `arb_cout_all_in` (REALISTE=16 bps).
FRAIS_ALLER_RETOUR_BPS = 13.0
#: demi-spread CONSERVATEUR par venue (bps) — un perp illiquide est plus large ; on assume large.
HALF_SPREAD_HL_BPS = 1.5
HALF_SPREAD_BIN_BPS = 0.75
#: impact à la taille réelle (on marche le carnet) — modélisé faute de profondeur capturée.
IMPACT_TAILLE_BPS = 2.0
#: 🔴 22/07 — au-delà, ce n'est PAS une dislocation : c'est un MAUVAIS APPARIEMENT (perp HL vs
#: perp Binance mal jumelés — décimales, wrapped, coin homonyme). La mesure brute a vu un
#: |écart| de 1 670 616 bps. Un tel écart n'est jamais exécutable ; le compter = fabriquer un
#: edge. Deny-by-default : un écart implausible est ÉCARTÉ, jamais capturé (mémoire « base aberrante »).
MAX_ECART_PLAUSIBLE_BPS = 500.0


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return None if x != x or x in (float("inf"), float("-inf")) else x


def cout_executable_bps(*, half_spread_hl_bps: float = HALF_SPREAD_HL_BPS,
                        half_spread_bin_bps: float = HALF_SPREAD_BIN_BPS,
                        impact_bps: float = IMPACT_TAILLE_BPS,
                        frais_aller_retour_bps: float = FRAIS_ALLER_RETOUR_BPS) -> float:
    """Coût aller-retour EXÉCUTABLE (bps) : frais 4 jambes + 4 franchissements de spread
    (entrée+sortie × 2 venues) + impact à la taille. Spread inconnu -> défauts LARGES."""
    hs_hl = max(0.0, _f(half_spread_hl_bps) or HALF_SPREAD_HL_BPS)
    hs_bin = max(0.0, _f(half_spread_bin_bps) or HALF_SPREAD_BIN_BPS)
    imp = max(0.0, _f(impact_bps) or 0.0)
    frais = max(0.0, _f(frais_aller_retour_bps) or FRAIS_ALLER_RETOUR_BPS)
    return round(frais + 2.0 * (hs_hl + hs_bin) + imp, 4)


def net_executable_bps(ecart_entree_bps: float, ecart_sortie_bps: float, *,
                       cout_bps: float | None = None, **kw: Any) -> float | None:
    """Net EXÉCUTABLE d'un trade : convergence capturée − coût exécutable. None si illisible."""
    e0, es = _f(ecart_entree_bps), _f(ecart_sortie_bps)
    if e0 is None or es is None:
        return None
    c = cout_bps if cout_bps is not None else cout_executable_bps(**kw)
    capture = abs(e0) - abs(es) if e0 * es > 0 else abs(e0) + abs(es)
    return round(capture - float(c), 4)


def verdict_population(signaux: Sequence[tuple[float, float]], *, seuil_bps: float = 19.0,
                      notional_usd: float = 50.0, **kw: Any) -> dict[str, Any]:
    """Sur une population de signaux (écart d'entrée, écart de sortie), combien SURVIVENT au prix
    exécutable, et pour quel PnL ? `signaux` : itérable de (ecart_entree, ecart_sortie).

    Verdict honnête : si le net exécutable moyen est ≤ 0, le +0,54 $ gaté était un mid-illusion —
    à confirmer/infirmer par la vraie capture de carnet (notée dans le doc du module)."""
    cout = cout_executable_bps(**kw)
    n = 0
    survivants = 0
    net_total_usd = 0.0
    ecartes_aberrants = 0
    for s in signaux or ():
        try:
            e0, es = float(s[0]), float(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        # 🔴 garde de plausibilité : un |écart| absurde = mauvais appariement, pas un edge.
        if abs(e0) > MAX_ECART_PLAUSIBLE_BPS or abs(es) > MAX_ECART_PLAUSIBLE_BPS:
            ecartes_aberrants += 1
            continue
        if abs(e0) < float(seuil_bps):
            continue
        net_bps = net_executable_bps(e0, es, cout_bps=cout)
        if net_bps is None:
            continue
        n += 1
        net_total_usd += net_bps / 1e4 * float(notional_usd)
        if net_bps > 0:
            survivants += 1
    moyen_usd = (net_total_usd / n) if n else 0.0
    if n == 0:
        verdict = "aucun signal au-dessus du seuil : rien a juger"
    elif net_total_usd > 0:
        verdict = ("au prix EXECUTABLE (modele conservateur, cout %.1f bps), la population reste "
                   "POSITIVE (%d/%d survivent) : signal encourageant, a confirmer par capture de "
                   "carnet reel" % (cout, survivants, n))
    else:
        verdict = ("au prix EXECUTABLE (modele conservateur, cout %.1f bps), la population NE "
                   "survit PAS (%d/%d, net %.4f $) : le +0,54 $ mesure au MID etait probablement "
                   "une illusion d'execution. Prochaine brique : capturer bid/ask+taille"
                   % (cout, survivants, n, round(net_total_usd, 4)))
    return {"signaux": n, "survivants": survivants, "cout_executable_bps": cout,
            "ecartes_aberrants": ecartes_aberrants,
            "net_total_usd": round(net_total_usd, 4), "net_moyen_usd": round(moyen_usd, 6),
            "verdict": verdict, "modele": True, "real_execution": False}


__all__ = ["FRAIS_ALLER_RETOUR_BPS", "HALF_SPREAD_HL_BPS", "HALF_SPREAD_BIN_BPS",
           "IMPACT_TAILLE_BPS", "cout_executable_bps", "net_executable_bps", "verdict_population"]
