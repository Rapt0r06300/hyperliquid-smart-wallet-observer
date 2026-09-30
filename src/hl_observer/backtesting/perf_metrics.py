"""Q1 + Q2 + Q3 — MÉTRIQUES ajustées du risque, décroissance roulante, analyse de QUEUE.

Q1 : Sharpe, Sortino (ne pénalise que la vol BAISSIÈRE), Calmar (rendement / max drawdown), profit
factor, payoff (gain moyen / perte moyenne) — on juge au risque, PAS au PnL brut.
Q3 : max drawdown, temps de récupération, pires pertes (le risque vit dans la queue gauche).
Q2 : la perf roulante décroche-t-elle (rupture) ? PUR. Deny-by-default : trop peu -> None. PAPER only.
"""
from __future__ import annotations

from typing import Sequence


def _ecart_type(xs, m):
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def sharpe(pnls: Sequence[float]) -> float | None:
    xs = [float(x) for x in pnls or []]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    sd = _ecart_type(xs, m)
    return 0.0 if sd <= 1e-12 else m / sd


def sortino(pnls: Sequence[float]) -> float | None:
    xs = [float(x) for x in pnls or []]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    bas = [x for x in xs if x < 0]
    if not bas:
        return float("inf") if m > 0 else 0.0
    dd = (sum(x ** 2 for x in bas) / len(xs)) ** 0.5
    return 0.0 if dd <= 1e-12 else m / dd


def profit_factor(pnls: Sequence[float]) -> float | None:
    gains = sum(x for x in pnls or [] if x > 0)
    pertes = -sum(x for x in pnls or [] if x < 0)
    if pertes <= 1e-12:
        return float("inf") if gains > 0 else None
    return gains / pertes


def payoff(pnls: Sequence[float]) -> float | None:
    g = [x for x in pnls or [] if x > 0]
    p = [-x for x in pnls or [] if x < 0]
    if not g or not p:
        return None
    return (sum(g) / len(g)) / (sum(p) / len(p))


def courbe_equity(pnls: Sequence[float]) -> list[float]:
    eq, cum = [], 0.0
    for x in pnls or []:
        cum += float(x)
        eq.append(cum)
    return eq


def max_drawdown(pnls: Sequence[float]) -> float:
    """Plus grande baisse depuis un sommet (positif = ampleur de la perte)."""
    pic, dd = float("-inf"), 0.0
    for e in courbe_equity(pnls):
        pic = max(pic, e)
        dd = max(dd, pic - e)
    return dd


def temps_recuperation(pnls: Sequence[float]) -> int | None:
    """Nombre de pas pour revenir au sommet précédent après le pire drawdown. None si jamais récupéré."""
    eq = courbe_equity(pnls)
    if not eq:
        return None
    pic = eq[0]; i_pic = 0; pire_dd = 0.0; i_creux = 0
    for i, e in enumerate(eq):
        if e > pic:
            pic, i_pic = e, i
        if pic - e > pire_dd:
            pire_dd, i_creux, i_pic_du_pire = pic - e, i, i_pic
    if pire_dd <= 0:
        return 0
    seuil = eq[i_pic_du_pire]
    for j in range(i_creux, len(eq)):
        if eq[j] >= seuil:
            return j - i_pic_du_pire
    return None                                        # jamais récupéré


def calmar(pnls: Sequence[float]) -> float | None:
    mdd = max_drawdown(pnls)
    total = sum(float(x) for x in pnls or [])
    if mdd <= 1e-12:
        return float("inf") if total > 0 else None
    return total / mdd


def perf_roulante_decroit(pnls: Sequence[float], *, fenetre: int = 20, fraction: float = 0.5) -> bool:
    """Q2 : True si la moyenne de la DERNIÈRE fenêtre est tombée sous `fraction` × la moyenne globale
    POSITIVE (l'edge décroche). Global <= 0 -> pas de décroissance mesurable."""
    xs = [float(x) for x in pnls or []]
    if len(xs) < int(fenetre) + 1:
        return False
    glob = sum(xs) / len(xs)
    if glob <= 0:
        return False
    recent = sum(xs[-int(fenetre):]) / int(fenetre)
    return recent < float(fraction) * glob


def panel(pnls: Sequence[float]) -> dict:
    return {"sharpe": sharpe(pnls), "sortino": sortino(pnls), "calmar": calmar(pnls),
            "profit_factor": profit_factor(pnls), "payoff": payoff(pnls),
            "max_drawdown": max_drawdown(pnls), "temps_recuperation": temps_recuperation(pnls)}


__all__ = ["sharpe", "sortino", "calmar", "profit_factor", "payoff", "courbe_equity",
           "max_drawdown", "temps_recuperation", "perf_roulante_decroit", "panel"]
