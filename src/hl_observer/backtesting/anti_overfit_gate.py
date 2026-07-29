"""#395 / M-19 — LE 7e CABLAGE MORT : nos garde-fous ANTI-OVERFIT n'etaient branches NULLE PART.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE L'AUDIT AST A TROUVE (2026-07-13)
═══════════════════════════════════════════════════════════════════════════════════════════════

SEPT garde-fous, tous marques « completed », tous avec **ZERO appelant de production** :

    deflated_sharpe                     (IDEA-22)   <- LA correction de multiplicite
    whites_reality_check                (IDEA-27)
    probability_of_backtest_overfitting (IDEA-23)
    purged_walk_forward_splits          (IDEA-30)
    combinatorial_purged_splits         (IDEA-21)
    min_track_record_length             (IDEA-28)
    probabilistic_sharpe_ratio          (appele seulement par deflated_sharpe... donc mort aussi)

Ils n'apparaissent QUE dans leur propre fichier de definition. Aucun autre fichier de `src/` ne
les nomme.

🔴 **ET ON A LANCE UNE RECHERCHE SUR 150 MILLIONS DE SCENARIOS.**

Le critere `robust` de `scenario_search` etait :

    net > 0 sur le TRAIN  ET  net > 0 sur le TEST  ET  gate  ET  plateau

Rien la-dedans ne corrige la **MULTIPLICITE**. Or c'est LE probleme quand on essaie 150 millions
de configurations : **le meilleur d'un tres grand nombre de tirages a l'air genial MEME SI TOUT
EST DU BRUIT.** Un holdout OOS aide, mais il ne suffit pas : en SELECTIONNANT le meilleur sur le
test, on sur-ajuste le test lui-meme.

H-181 avait deja trouve le symptome -- *« on selectionne les 40 plus CHANCEUSES »* -- **sans voir
que le garde-fou cense l'attraper etait MORT.**

🚩 Et il y a deux heures, mon propre outil de cointegration a imprime : *« controle de
multiplicite exige (Deflated Sharpe / White's Reality Check -- **deja codes**, IDEA-22/27) »*.
**J'ai cite un garde-fou qui ne tourne pas.** Comme le `LatencyTracker` de #251.
*Un module qui existe n'est pas un module qui garde.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE MODULE : le gate qui manquait. Il refuse un finaliste dont le Sharpe ne survit pas a la
DEFLATION par le nombre d'essais reellement effectues.

DENY-BY-DEFAULT : `n_essais` inconnu ou <= 0 -> **REFUS**. On ne peut pas juger un vainqueur si
on ignore contre combien de concurrents il a gagne.

Aucun ordre reel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from hl_observer.backtesting.quant_methods import deflated_sharpe

# Sous ce seuil, le Sharpe deflate n'est pas distinguable du hasard.
# 0,95 = « moins de 5 % de chance que ce resultat soit du bruit, COMPTE TENU du nombre d'essais ».
PROBA_MIN = 0.95

# Sous ce nombre de trades, un Sharpe n'a aucun sens (variance de l'estimateur trop grande).
MIN_TRADES = 25

MOTIF_ESSAIS_INCONNUS = "NOMBRE_D_ESSAIS_INCONNU_ON_NE_PEUT_PAS_DEFLATER_NO_TRADE"
MOTIF_TROP_PEU_DE_TRADES = "TROP_PEU_DE_TRADES_POUR_UN_SHARPE_NO_TRADE"
MOTIF_NOISE = "SHARPE_NON_DISTINGUABLE_DU_BRUIT_APRES_DEFLATION_PAR_LE_NOMBRE_D_ESSAIS"
MOTIF_OK = "SHARPE_SURVIT_A_LA_DEFLATION"


def sharpe(pnls: Sequence[float]) -> float:
    """Sharpe brut d'une serie de PnL par trade. Pas d'annualisation : on compare des tirages
    entre eux, pas a un indice."""
    n = len(pnls)
    if n < 2:
        return 0.0
    m = sum(pnls) / n
    var = sum((x - m) ** 2 for x in pnls) / (n - 1)
    sd = math.sqrt(var)
    return (m / sd) if sd > 0 else 0.0


@dataclass(frozen=True, slots=True)
class VerdictAntiOverfit:
    sharpe_brut: float
    n_trades: int
    n_essais: int
    proba_deflatee: float       # P(le vrai Sharpe > 0 | on a essaye n_essais fois)
    survit: bool
    motif: str
    note: str = ""
    n_sharpes_distribution: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "sharpe_brut": round(self.sharpe_brut, 4),
            "n_trades": self.n_trades,
            "n_essais": self.n_essais,
            "proba_deflatee": round(self.proba_deflatee, 6),
            "survit": self.survit,
            "motif": self.motif,
            "note": self.note,
            "n_sharpes_distribution": self.n_sharpes_distribution,
            "real_execution": False,
        }


def evaluer(
    pnls: Sequence[float],
    *,
    n_essais: int,
    proba_min: float = PROBA_MIN,
    trial_sharpes: Sequence[float] | None = None,
) -> VerdictAntiOverfit:
    """Ce finaliste survit-il a la DEFLATION par le nombre d'essais ?

    `n_essais` = **combien de configurations ont ete testees avant de choisir celle-ci.**
    Ce n'est PAS un detail : c'est la variable qui decide. Choisir le meilleur de 150 000 000
    tirages de bruit pur donne un Sharpe magnifique -- et parfaitement vide.
    """
    n = len(pnls)
    if n_essais <= 0:
        return VerdictAntiOverfit(
            0.0, n, int(n_essais), 0.0, False, MOTIF_ESSAIS_INCONNUS,
            "on ignore contre combien de concurrents ce scenario a gagne : on ne peut PAS juger "
            "son merite. *Un vainqueur sans course n'est pas un champion.*",
        )
    if n < MIN_TRADES:
        return VerdictAntiOverfit(
            0.0, n, int(n_essais), 0.0, False, MOTIF_TROP_PEU_DE_TRADES,
            "%d trades < %d : la variance de l'estimateur de Sharpe ecrase tout." % (n, MIN_TRADES),
        )

    sr = sharpe(pnls)
    distribution = tuple(float(value) for value in (trial_sharpes or ()))
    p = float(
        deflated_sharpe(
            sr,
            n,
            int(n_essais),
            trial_sharpes=distribution,
        )
    )
    survit = p >= float(proba_min)
    return VerdictAntiOverfit(
        sr, n, int(n_essais), p, survit,
        MOTIF_OK if survit else MOTIF_NOISE,
        "Sharpe brut %.3f sur %d trades, choisi parmi **%d essais** -> probabilite deflatee "
        "%.4f (seuil %.2f). %s"
        % (sr, n, n_essais, p, proba_min,
           "Il survit." if survit else
           "**Il ne survit pas.** Le meilleur d'un tres grand nombre de tirages a l'air genial "
           "meme si tout est du bruit."),
        len(distribution),
    )


__all__ = [
    "MIN_TRADES", "MOTIF_ESSAIS_INCONNUS", "MOTIF_NOISE", "MOTIF_OK",
    "MOTIF_TROP_PEU_DE_TRADES", "PROBA_MIN",
    "VerdictAntiOverfit", "evaluer", "sharpe",
]
