"""A5 — CONVERGENCE DE BASE : le 2e PnL du carry, en plus du funding.

Carry delta-neutre = long spot + short perp. Le prix s'annule, MAIS l'ECART spot-perp (la base)
bouge : notre paire gagne (base_entree − base_courant) quand le spread se resserre en notre faveur.
C'est un 2e PnL, plus rapide que le funding (une base favorable donne un break-even d'~1h).

⚠️ HONNETETE : le modele de cout (delta_neutral_carry) CREDITE deja toute la base a l'ENTREE
(cout_entree = frais − base). C'est OPTIMISTE : on ne capture la base que si elle CONVERGE.
Ce module fournit :
  * la correction honnete a appliquer a la SORTIE (retirer la base residuelle non capturee) ;
  * un signal 'base convergee' pour verrouiller le premium quand il est capture.

PAPER only : aucun ordre, aucune signature.
"""
from __future__ import annotations

BASE_FAVORABLE_MIN_BPS = 2.0     # en-deca, la base est du bruit (pas un premium a jouer)
FRACTION_CONVERGENCE = 0.7       # 'base convergee' = >= 70 % du premium d'entree capture


def capture_base_bps(base_entree_bps: float, base_courant_bps: float) -> float:
    """Le VRAI P&L de base sur la periode (bps, notre cote) : base_entree − base_courant.
    Positif = le spread s'est resserre en notre faveur (on a capture du premium)."""
    return float(base_entree_bps) - float(base_courant_bps)


def correction_sortie_bps(base_courant_bps: float) -> float:
    """Correction HONNETE a la sortie. Le modele a credite toute la base d'entree ; on RETIRE la
    base residuelle non encore capturee (= base_courant). A ajouter au realized (souvent negatif).

    net_base_realise = base_entree (credite par le cout) + correction = base_entree − base_courant
    = le vrai P&L de base. Base pas convergee -> on ne garde AUCUN premium fantome."""
    return -float(base_courant_bps)


def base_convergee(base_entree_bps: float, base_courant_bps: float, *,
                   fraction: float = FRACTION_CONVERGENCE,
                   min_bps: float = BASE_FAVORABLE_MIN_BPS) -> bool:
    """True si la base d'entree etait un premium REEL (|base_entree| >= min_bps) ET qu'il a converge
    (il reste <= (1−fraction) du premium). Signal pour verrouiller le 2e PnL."""
    be = float(base_entree_bps)
    if abs(be) < float(min_bps):
        return False                                  # base d'entree negligeable -> rien a verrouiller
    return abs(float(base_courant_bps)) <= (1.0 - float(fraction)) * abs(be)


__all__ = ["BASE_FAVORABLE_MIN_BPS", "FRACTION_CONVERGENCE",
           "capture_base_bps", "correction_sortie_bps", "base_convergee"]
