"""LA REGLE DE NOTATION *EST* LA STRATEGIE (2026-07-12).

    « The scoring rule is the strategy. Everything downstream is just search. »
    « Score raw returns, and it will find the most overfit curve in your dataset. »

C'est la phrase la plus juste de tout le framework, et c'est celle qu'on oublie.

Un agent optimise CE QU'ON NOTE. Notez le rendement brut : il trouvera la courbe la plus
surajustee du dataset. Notez le winrate : il fera 99 trades a +1 $ et un a -200 $. Notez le
Sharpe sur 20 trades : il trouvera du bruit qui ressemble a du talent.

CE MODULE : un score COMPOSITE, qui refuse de se laisser tromper par une seule dimension.

    1. PROFIT FACTOR    -- gains / pertes. Pas le winrate : un winrate de 89 % avec PF 0,4
                           est une machine a perdre (mesure, session du 08/07).
    2. DRAWDOWN         -- une equity qui monte en passant par -40 % n'est pas exploitable.
    3. NOMBRE DE TRADES -- 3 trades gagnants ne sont pas une strategie, c'est de la chance.
    4. STABILITE        -- le meme resultat sur des fenetres differentes. Une config qui ne gagne
                           que sur une fenetre a MEMORISE cette fenetre.

VETO, PAS MOYENNE. Un score composite qui MOYENNE ses composantes laisse un PF de reve compenser
un drawdown mortel. Ici, chaque composante a un PLANCHER : un seul echec = zero. On ne negocie
pas avec la ruine.

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Sequence

# Planchers. En dessous : ZERO. Pas de moyenne, pas de compensation.
PF_MIN = 1.15                  # sous 1,15, la marge est mangee par la premiere surprise
DRAWDOWN_MAX_PCT = 20.0        # au-dela, on ne tient pas psychologiquement ni financierement
TRADES_MIN = 30                # sous 30, c'est du bruit qui ressemble a du talent
STABILITE_MIN = 0.5            # il faut gagner sur au moins la moitie des fenetres

MOTIF_PF = "PROFIT_FACTOR_TROP_FAIBLE"
MOTIF_DD = "DRAWDOWN_INACCEPTABLE"
MOTIF_N = "TROP_PEU_DE_TRADES"
MOTIF_STABILITE = "INSTABLE_ENTRE_FENETRES"
MOTIF_VIDE = "AUCUNE_DONNEE"


@dataclass(frozen=True, slots=True)
class Fitness:
    score: float                          # 0 = rejete. > 0 = candidat.
    profit_factor: float
    drawdown_pct: float
    n_trades: int
    stabilite: float                      # part des fenetres gagnantes
    motifs_de_rejet: tuple[str, ...]
    accepte: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score, "profit_factor": self.profit_factor,
            "drawdown_pct": self.drawdown_pct, "n_trades": self.n_trades,
            "stabilite": self.stabilite,
            "motifs_de_rejet": list(self.motifs_de_rejet),
            "accepte": self.accepte,
            "regle": (
                "VETO, pas moyenne : un seul plancher franchi = score 0. Un PF de reve ne rachete "
                "pas un drawdown mortel."
            ),
            "real_execution": False,
        }


def profit_factor(pnls: Sequence[float]) -> float:
    """Gains / pertes. Le seul chiffre qui ne ment pas sur la distribution.

    Un winrate de 89 % avec 2 pertes qui mangent 17 gains donne un PF de 0,4 : la machine perd.
    C'est EXACTEMENT ce qu'on a mesure le 2026-07-08. Le winrate est un mensonge confortable.
    """
    gains = sum(p for p in pnls if p > 0)
    pertes = -sum(p for p in pnls if p < 0)
    if pertes <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / pertes


def drawdown_pct(pnls: Sequence[float], capital: float = 1000.0) -> float:
    """Le pire creux depuis un sommet, en %. Ce que ca fait VRAIMENT de le vivre."""
    if not pnls or capital <= 0:
        return 0.0
    equity = capital
    sommet = capital
    pire = 0.0
    for p in pnls:
        equity += p
        sommet = max(sommet, equity)
        if sommet > 0:
            pire = max(pire, (sommet - equity) / sommet * 100.0)
    return pire


def stabilite(fenetres: Sequence[Sequence[float]]) -> float:
    """Part des fenetres ou la strategie gagne. Une config qui ne gagne QUE sur une fenetre
    a memorise cette fenetre -- c'est le surajustement, vu de face."""
    if not fenetres:
        return 0.0
    gagnantes = sum(1 for f in fenetres if f and sum(f) > 0)
    return gagnantes / len(fenetres)


def evaluer(
    pnls: Sequence[float],
    *,
    fenetres: Sequence[Sequence[float]] | None = None,
    capital: float = 1000.0,
) -> Fitness:
    """LE score. DENY-BY-DEFAULT : sans donnee, zero. Jamais de benefice du doute."""
    if not pnls:
        return Fitness(0.0, 0.0, 0.0, 0, 0.0, (MOTIF_VIDE,), False)

    pf = profit_factor(pnls)
    dd = drawdown_pct(pnls, capital)
    n = len(pnls)
    st = stabilite(fenetres) if fenetres else 0.0

    motifs: list[str] = []
    if n < TRADES_MIN:
        motifs.append(MOTIF_N)
    if not math.isfinite(pf) or pf < PF_MIN:
        motifs.append(MOTIF_PF)
    if dd > DRAWDOWN_MAX_PCT:
        motifs.append(MOTIF_DD)
    if fenetres is None or st < STABILITE_MIN:
        motifs.append(MOTIF_STABILITE)

    if motifs:
        # VETO : un seul plancher franchi -> ZERO. On ne moyenne pas avec la ruine.
        return Fitness(0.0, round(pf, 4) if math.isfinite(pf) else 0.0,
                       round(dd, 2), n, round(st, 3), tuple(motifs), False)

    # Le score ne recompense pas la performance brute : il recompense la ROBUSTESSE.
    # PF au-dessus du plancher x stabilite x (marge de drawdown restante).
    marge_dd = max(0.0, 1.0 - dd / DRAWDOWN_MAX_PCT)
    score = (pf - PF_MIN) * st * (0.5 + 0.5 * marge_dd)
    return Fitness(round(score, 4), round(pf, 4), round(dd, 2), n, round(st, 3), (), True)


def comparer(a: Fitness, b: Fitness) -> Fitness:
    """Le meilleur des deux. Un rejete ne bat JAMAIS un accepte, quel que soit son score."""
    if a.accepte != b.accepte:
        return a if a.accepte else b
    return a if a.score >= b.score else b


__all__ = [
    "DRAWDOWN_MAX_PCT", "MOTIF_DD", "MOTIF_N", "MOTIF_PF", "MOTIF_STABILITE", "MOTIF_VIDE",
    "PF_MIN", "STABILITE_MIN", "TRADES_MIN",
    "Fitness", "comparer", "drawdown_pct", "evaluer", "profit_factor", "stabilite",
]
