"""L'ARITHMÉTIQUE AVANT LE SIGNAL — une config peut être perdante par construction (2026-07-11).

CE QUE CE MODULE EMPÊCHE (pistes 41-50 du brief).

Avant de se demander si un signal est bon, il faut se demander si la configuration **peut** gagner.
Souvent, non — et aucun signal, aussi parfait soit-il, n'y changera rien :

    take-profit 28 bps  |  stop-loss 126 bps  |  coût aller-retour 13 bps
    → il faut viser 28 pour en garder 15, et risquer 126 + 13 = 139
    → winrate d'équilibre = 139 / (139 + 15) = **90 %**

Aucune stratégie ne fait 90 %. **La perte était garantie avant le premier trade.** C'est très
exactement ce qui s'est produit : le facteur de volatilité rabotait le TP à 28 bps pour 13 bps de
frais. Le −64 $ n'était pas de la malchance, c'était de l'arithmétique.

Le brief donne les vrais chiffres Hyperliquid : taker 0,045 % (4,5 bps), maker 0,015 % (1,5 bps).
Un aller-retour taker coûte donc **9 bps**, avant même le spread, le slippage et le funding.

CE MODULE :
  * calcule le winrate d'équilibre RÉEL, coûts inclus ;
  * rend un VERDICT : VIABLE / EXIGEANT / IMPOSSIBLE ;
  * ne promet AUCUN PnL. Il dit seulement quand gagner est arithmétiquement hors d'atteinte.

Un winrate d'équilibre au-dessus de ~65 % doit être traité comme une alarme : les meilleurs
systèmes directionnels tournent entre 40 % et 60 %. Au-dessus de 80 %, c'est un mur.

PUR, sans I/O, sans réseau. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass

# Tarif de base Hyperliquid, verifie 2026-07-11 (fourni par Flo).
TAKER_BPS = 4.5
MAKER_BPS = 1.5          # le maker COUTE : le rebate n'existe qu'aux hauts paliers de volume

# Seuils de jugement. Ils ne sont pas arbitraires :
#   * un systeme directionnel serieux tourne entre 40 % et 60 % de winrate ;
#   * au-dela de 65 %, il faut une raison EXTRAORDINAIRE d'y croire ;
#   * au-dela de 80 %, c'est un mur : la config perd par construction.
SEUIL_EXIGEANT = 0.65
SEUIL_IMPOSSIBLE = 0.80

VIABLE = "VIABLE"
EXIGEANT = "EXIGEANT"
IMPOSSIBLE = "IMPOSSIBLE"


def cout_aller_retour_bps(*, maker_entree: bool = False, maker_sortie: bool = False,
                          spread_bps: float = 0.0, slippage_bps: float = 0.0) -> float:
    """Coût complet d'un aller-retour, en bps. On n'oublie AUCUNE jambe."""
    entree = MAKER_BPS if maker_entree else TAKER_BPS
    sortie = MAKER_BPS if maker_sortie else TAKER_BPS
    return entree + sortie + max(0.0, float(spread_bps)) + max(0.0, float(slippage_bps))


@dataclass(frozen=True, slots=True)
class Economie:
    take_profit_bps: float
    stop_loss_bps: float
    cout_aller_retour_bps: float
    gain_net_si_gagne_bps: float
    perte_nette_si_perd_bps: float
    winrate_equilibre: float | None      # None = gagner est IMPOSSIBLE (le TP ne couvre pas le coût)
    verdict: str
    explication: str

    def as_dict(self) -> dict:
        return {
            "take_profit_bps": round(self.take_profit_bps, 4),
            "stop_loss_bps": round(self.stop_loss_bps, 4),
            "cout_aller_retour_bps": round(self.cout_aller_retour_bps, 4),
            "gain_net_si_gagne_bps": round(self.gain_net_si_gagne_bps, 4),
            "perte_nette_si_perd_bps": round(self.perte_nette_si_perd_bps, 4),
            "winrate_equilibre": (round(self.winrate_equilibre, 4)
                                  if self.winrate_equilibre is not None else None),
            "verdict": self.verdict,
            "explication": self.explication,
        }


def evaluer_economie(
    *,
    take_profit_bps: float,
    stop_loss_bps: float,
    cout_bps: float,
) -> Economie:
    """Cette configuration PEUT-ELLE gagner ? Question posée AVANT celle du signal.

    Le coût frappe les deux issues : on ne garde que (TP − coût) quand on gagne, et on perd
    (SL + coût) quand on perd. Oublier ce détail est exactement ce qui rend un backtest menteur.
    """
    tp = max(0.0, float(take_profit_bps))
    sl = max(0.0, float(stop_loss_bps))
    cout = max(0.0, float(cout_bps))

    gain = tp - cout                      # ce qu'on garde VRAIMENT quand on a raison
    perte = sl + cout                     # ce qu'on paie VRAIMENT quand on a tort

    if gain <= 0.0:
        return Economie(
            take_profit_bps=tp, stop_loss_bps=sl, cout_aller_retour_bps=cout,
            gain_net_si_gagne_bps=gain, perte_nette_si_perd_bps=perte,
            winrate_equilibre=None,
            verdict=IMPOSSIBLE,
            explication=(
                f"l'objectif ({tp:.1f} bps) ne couvre meme pas le cout ({cout:.1f} bps) : "
                f"un trade GAGNANT rapporte {gain:.1f} bps. Gagner est arithmetiquement impossible, "
                f"quel que soit le signal."
            ),
        )
    if perte <= 0.0:                      # pas de stop et pas de cout : cas degenere, non juge
        return Economie(
            take_profit_bps=tp, stop_loss_bps=sl, cout_aller_retour_bps=cout,
            gain_net_si_gagne_bps=gain, perte_nette_si_perd_bps=perte,
            winrate_equilibre=0.0, verdict=VIABLE,
            explication="aucun stop et aucun cout : configuration degeneree, non jugeable.",
        )

    breakeven = perte / (perte + gain)

    if breakeven >= SEUIL_IMPOSSIBLE:
        verdict = IMPOSSIBLE
        explication = (
            f"il faut avoir raison {breakeven*100:.0f} % du temps pour ne RIEN gagner. "
            f"Aucun systeme directionnel ne tient ce rythme : la perte est structurelle, "
            f"pas accidentelle."
        )
    elif breakeven >= SEUIL_EXIGEANT:
        verdict = EXIGEANT
        explication = (
            f"winrate d'equilibre {breakeven*100:.0f} % : tres au-dessus des 40-60 % d'un systeme "
            f"directionnel serieux. Exige une raison extraordinaire d'y croire."
        )
    else:
        verdict = VIABLE
        explication = (
            f"winrate d'equilibre {breakeven*100:.0f} % : atteignable en principe. "
            f"Cela ne PROMET aucun gain -- cela dit seulement que gagner n'est pas exclu d'avance."
        )

    return Economie(
        take_profit_bps=tp, stop_loss_bps=sl, cout_aller_retour_bps=cout,
        gain_net_si_gagne_bps=gain, perte_nette_si_perd_bps=perte,
        winrate_equilibre=breakeven, verdict=verdict, explication=explication,
    )


def edge_minimum_requis_bps(*, cout_bps: float, marge_securite_bps: float = 5.0) -> float:
    """En dessous de ce mouvement attendu, un trade est une perte esperee. Plancher dur.

    Ce n'est pas de la prudence : c'est le seuil sous lequel l'esperance est NEGATIVE par
    construction. La marge de securite couvre l'erreur de mesure du coût lui-meme.
    """
    return max(0.0, float(cout_bps)) + max(0.0, float(marge_securite_bps))


__all__ = [
    "EXIGEANT",
    "IMPOSSIBLE",
    "MAKER_BPS",
    "SEUIL_EXIGEANT",
    "SEUIL_IMPOSSIBLE",
    "TAKER_BPS",
    "VIABLE",
    "Economie",
    "cout_aller_retour_bps",
    "edge_minimum_requis_bps",
    "evaluer_economie",
]
