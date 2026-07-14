"""#571 / H-166 + #567 + #573 + #574 + #579 — LES MÉTRIQUES QU'ON N'AVAIT PAS.

═══════════════════════════════════════════════════════════════════════════════════════════════
#571 — LA QUESTION QU'ON N'A JAMAIS POSÉE : **et si on n'avait RIEN fait ?**
═══════════════════════════════════════════════════════════════════════════════════════════════

Le projet a produit des dizaines de rapports de PnL. **Aucun** n'a jamais affiche le
**buy-and-hold** a cote.

    ***Un edge mesure a -7,97 bps est battu par NE RIEN FAIRE.***
    Et « ne rien faire » n'a ni frais, ni spread, ni slippage, ni latence, ni liquidation.

Le buy-and-hold n'est pas un detail cosmetique : **c'est le benchmark que toute strategie doit
battre pour justifier son existence.** Ne pas l'afficher, c'est se donner un adversaire imaginaire.

⚠️ HONNETETE : le buy-and-hold n'est PAS « sans risque ». Il subit tout le drawdown du marche.
Une strategie qui perd moins qu'un B&H en baisse a une valeur -- **il faut donc comparer les
DEUX : le rendement ET le drawdown.** C'est ce que fait `comparer_au_buy_and_hold`.

═══════════════════════════════════════════════════════════════════════════════════════════════
#567 + #573 — **DEUX DRAWDOWNS, DEUX SHARPE. ILS DIFFERENT.**
═══════════════════════════════════════════════════════════════════════════════════════════════

  * **drawdown sur trades CLOTURES** : la courbe ne bouge qu'a la sortie. Elle CACHE la douleur
    vecue pendant qu'une position perdante etait ouverte.
  * **drawdown sur l'EQUITY (wallet)** : la courbe bouge a chaque tick. **C'est celui qu'on vit.**

***Le premier est TOUJOURS plus flatteur.*** Publier le premier en le nommant « drawdown », c'est
maquiller -- meme sans le vouloir. On calcule **les deux**, et on affiche l'ECART.

═══════════════════════════════════════════════════════════════════════════════════════════════
#574 — L'ESPERANCE : la metrique qui manquait
═══════════════════════════════════════════════════════════════════════════════════════════════

    esperance = winrate x gain_moyen - (1 - winrate) x perte_moyenne

C'est le **gain attendu par trade**. Un winrate de 87 % avec une esperance negative reste une
machine a perdre -- et c'est **exactement ce que l'autopsie du -64 $ a trouve** (breakeven 87 %).

═══════════════════════════════════════════════════════════════════════════════════════════════
#579 — OPTIMISER LE PIRE MARCHE, PAS LA MOYENNE
═══════════════════════════════════════════════════════════════════════════════════════════════

Une moyenne cache un desastre. T2b l'a fait correctement : le carry HYPE a ete juge sur son
**PIRE mois**. On generalise : `pire_periode()`.

PUR : aucun appel reseau. Aucun ordre reel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

MOTIF_PAS_ASSEZ_DE_TRADES = "PAS_ASSEZ_DE_TRADES_POUR_UNE_METRIQUE_HONNETE"
MIN_TRADES = 20          # sous ce seuil, un chiffre n'est qu'une anecdote


@dataclass(frozen=True, slots=True)
class DoubleDrawdown:
    """#567 / #573 — le drawdown FLATTEUR et le drawdown VECU."""
    dd_trades_clotures: float      # sur la courbe qui ne bouge qu'aux sorties
    dd_equity: float               # sur la courbe qui bouge a chaque tick
    ecart: float                   # ce que le 1er CACHAIT

    def as_dict(self) -> dict[str, Any]:
        return {"dd_trades_clotures": round(self.dd_trades_clotures, 4),
                "dd_equity": round(self.dd_equity, 4),
                "ecart_cache": round(self.ecart, 4),
                "note": ("Le drawdown sur trades clotures est TOUJOURS <= celui de l'equity : "
                         "il cache la douleur des positions ouvertes. **On publie les deux.**")}


@dataclass(frozen=True, slots=True)
class ComparaisonBuyAndHold:
    """#571 — le benchmark qu'on n'a JAMAIS affiche."""
    rendement_strategie: float
    rendement_buy_and_hold: float
    dd_strategie: float
    dd_buy_and_hold: float
    bat_le_rendement: bool
    bat_le_drawdown: bool

    @property
    def domine_par_le_cash(self) -> bool:
        """🔴 **LE BENCHMARK QUE J'AVAIS OUBLIE, ET C'EST LE PLUS TRIVIAL : LE CASH.**

        Ma 1re version disait : « une strategie se justifie si elle bat le B&H en rendement **OU**
        en drawdown ». **Un test rouge l'a demolie** : une strategie qui PERD 5 % pendant que le
        marche MONTE de 20 % etait declaree « justifiee », au motif que son drawdown etait plus
        petit que celui du marche.

        **Absurde.** Le cash rend 0 % avec 0 % de drawdown. *Toute strategie a rendement negatif
        est dominee par NE RIEN FAIRE DU TOUT, sur les DEUX dimensions a la fois.*

        Et notre edge mesure est de **-7,97 bps**. **On est dans ce cas.**
        """
        return self.rendement_strategie <= 0.0

    @property
    def justifie_son_existence(self) -> bool:
        """Deux barres, pas une :

          1. **ne pas etre dominee par le CASH** (rendement > 0) ;
          2. **battre le buy-and-hold** sur au moins une dimension (rendement OU drawdown).

        ⚠️ Le B&H n'est PAS sans risque : perdre moins que lui en krach a une vraie valeur.
        C'est pourquoi la 2e barre accepte le drawdown. Mais la 1re est **non negociable**.
        """
        return (not self.domine_par_le_cash) and (self.bat_le_rendement or self.bat_le_drawdown)

    def as_dict(self) -> dict[str, Any]:
        if self.domine_par_le_cash:
            verdict = ("🔴 **DOMINEE PAR LE CASH.** Rendement <= 0 : ne RIEN faire du tout aurait "
                       "ete meilleur, en rendement ET en drawdown. Aucun argument ne sauve ca.")
        elif not self.justifie_son_existence:
            verdict = ("La strategie ne bat le buy-and-hold NI en rendement NI en drawdown. "
                       "**Acheter et ne plus y toucher aurait ete meilleur.**")
        else:
            verdict = "La strategie bat le cash, et le buy-and-hold sur au moins une dimension."
        return {
            "rendement_strategie": round(self.rendement_strategie, 4),
            "rendement_buy_and_hold": round(self.rendement_buy_and_hold, 4),
            "rendement_cash": 0.0,
            "dd_strategie": round(self.dd_strategie, 4),
            "dd_buy_and_hold": round(self.dd_buy_and_hold, 4),
            "dd_cash": 0.0,
            "bat_le_rendement": self.bat_le_rendement,
            "bat_le_drawdown": self.bat_le_drawdown,
            "domine_par_le_cash": self.domine_par_le_cash,
            "justifie_son_existence": self.justifie_son_existence,
            "verdict": verdict,
        }


@dataclass(frozen=True, slots=True)
class Esperance:
    """#574 — le gain ATTENDU par trade. Un winrate n'est pas une esperance."""
    n_trades: int
    winrate: float
    gain_moyen: float
    perte_moyenne: float        # valeur ABSOLUE
    esperance: float
    profit_factor: float | None
    suffisant: bool
    motif: str = ""

    @property
    def winrate_de_breakeven(self) -> float | None:
        """Le winrate qu'il FAUDRAIT pour etre a l'equilibre. Si > le reel : machine a perdre."""
        d = self.gain_moyen + self.perte_moyenne
        return (self.perte_moyenne / d) if d > 0 else None

    def as_dict(self) -> dict[str, Any]:
        return {"n_trades": self.n_trades, "winrate": round(self.winrate, 4),
                "gain_moyen": round(self.gain_moyen, 4),
                "perte_moyenne": round(self.perte_moyenne, 4),
                "esperance": round(self.esperance, 6),
                "profit_factor": (round(self.profit_factor, 4)
                                  if self.profit_factor is not None else None),
                "winrate_de_breakeven": (round(self.winrate_de_breakeven, 4)
                                         if self.winrate_de_breakeven is not None else None),
                "suffisant": self.suffisant, "motif": self.motif}


def _drawdown_max(courbe: Sequence[float]) -> float:
    """Drawdown maximal, en fraction du sommet. 0 si la courbe ne baisse jamais."""
    if not courbe:
        return 0.0
    sommet = courbe[0]
    pire = 0.0
    for v in courbe:
        if v > sommet:
            sommet = v
        if sommet > 0:
            dd = (sommet - v) / sommet
            if dd > pire:
                pire = dd
    return pire


def double_drawdown(
    equity_par_tick: Sequence[float],
    equity_aux_cloture: Sequence[float],
) -> DoubleDrawdown:
    """🔴 Les deux courbes, les deux drawdowns, et l'ECART que le premier cachait."""
    dd_c = _drawdown_max(equity_aux_cloture)
    dd_e = _drawdown_max(equity_par_tick)
    return DoubleDrawdown(dd_trades_clotures=dd_c, dd_equity=dd_e, ecart=dd_e - dd_c)


def buy_and_hold(prix: Sequence[float]) -> tuple[float, float]:
    """(rendement, drawdown) de « acheter au debut, ne plus rien faire ».

    **Aucun frais, aucun spread, aucun slippage, aucune latence, aucune liquidation.**
    C'est l'adversaire le plus honnete qui soit -- et le plus dur a battre.
    """
    ps = [float(p) for p in prix if p and float(p) > 0]
    if len(ps) < 2:
        return 0.0, 0.0
    return (ps[-1] / ps[0]) - 1.0, _drawdown_max(ps)


def comparer_au_buy_and_hold(
    equity_strategie: Sequence[float],
    prix_du_marche: Sequence[float],
) -> ComparaisonBuyAndHold:
    """#571 — **LE BENCHMARK QU'ON N'A JAMAIS AFFICHE.**"""
    eq = [float(e) for e in equity_strategie]
    r_bh, dd_bh = buy_and_hold(prix_du_marche)
    r_s = ((eq[-1] / eq[0]) - 1.0) if len(eq) >= 2 and eq[0] > 0 else 0.0
    dd_s = _drawdown_max(eq)
    return ComparaisonBuyAndHold(
        rendement_strategie=r_s, rendement_buy_and_hold=r_bh,
        dd_strategie=dd_s, dd_buy_and_hold=dd_bh,
        bat_le_rendement=r_s > r_bh,
        bat_le_drawdown=dd_s < dd_bh,
    )


def esperance(pnls: Sequence[float], *, min_trades: int = MIN_TRADES) -> Esperance:
    """#574 — winrate x gain - (1-winrate) x perte. **Un winrate n'est pas une esperance.**"""
    xs = [float(p) for p in pnls]
    n = len(xs)
    if n < min_trades:
        return Esperance(n_trades=n, winrate=0.0, gain_moyen=0.0, perte_moyenne=0.0,
                         esperance=0.0, profit_factor=None, suffisant=Fal