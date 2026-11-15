"""LIVRE TRANSVERSAL INVERSE — le SEUL sens qui mesure positif, et celui que le moteur n'a pas.

⚠ AVERTISSEMENT SUR `carry_ranking` : ce module-la classe par **carry net predit par heure**, donc
il LONGE le funding bas et SHORTE le funding haut. **C'est le sens REFUTE** : mesure du 14/11 sur
211 jours, 90 coins, prix compris, **-41,3 %/an, 8 detentions positives sur 25**. Le funding
rapportait bien +1,635 % par detention, mais le prix en reprenait **-4,901 %** — trois fois plus.
`carry_ranking` reste en place parce qu'il a servi a etablir cette refutation ; **il ne doit pas
etre ce que le moteur ouvre.**

LE SENS QUI MESURE POSITIF, ET POURQUOI
---------------------------------------
On **LONGE le funding le plus HAUT** et on **SHORTE le plus BAS**. On PAIE donc le funding sur les
deux jambes (-1,8 % par detention) et on gagne sur le prix (+5,3 %).

La raison n'est pas « le momentum marche » : **le momentum direct a ete mesure a -44,2 %**, negatif
a tous les `k` et toutes les ponderations. Le funding porte donc une information que le rendement
passe ne contient PAS — il mesure **l'ENCOMBREMENT DU POSITIONNEMENT**, pas la performance. Un
funding eleve dit « la foule est deja longue ici », et c'est cela qui persiste.

LES DEUX JAMBES SONT NECESSAIRES
--------------------------------
La jambe longue perd **-9,2 %/an** prise seule. On la garde quand meme : sans elle le repli passe de
12,1 % a **42,7 %** et la correlation au marche de +0,19 a **-0,80**. Apres dimensionnement, deux
jambes rendent **+80,8 %/an contre +54,4 %** pour le short seul. **Elle se paie en RISQUE, pas en
rendement** — c'est une assurance, et le balayage du taux de couverture est monotone en sa faveur.

CE QUE CE MODULE REFUSE
-----------------------
* **moins de `2k` coins classables** -> aucune proposition. Construire un livre plus petit en
  silence changerait la strategie sans le dire ;
* **une jambe sous le notionnel minimum de la venue** -> aucune proposition. Un ordre de 4 USD n'est
  pas une petite position, c'est un ordre REJETE : proposer un livre non placable serait proposer
  un livre qui n'existera pas ;
* **une fenetre de classement qui touche l'instant de decision** -> la moyenne EXCLUT la borne
  haute. Inclure l'heure de decision ferait entrer une information qu'on n'avait pas : c'est la
  frontiere exacte entre une mesure et un lookahead.

Module PUR et deterministe, comme tout `strategies/` : il PROPOSE des intentions. **Le noyau
dispose** — chaque entree repasse par les frais reels, les prix executables et la profondeur. Un
classement n'est pas un ordre, et une intention n'est pas une execution.

PAPER / lecture seule.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hl_observer.storage.run_context import RunContext
from hl_observer.strategies.models import (
    IntentAction,
    IntentSide,
    PaperIntent,
    StrategyKind,
    make_strategy,
)

#: Notionnel minimum par ordre sur Hyperliquid, en USD. Une jambe en dessous est REJETEE.
NOTIONNEL_MINIMUM_USD = 10.0

#: Conventions du protocole gele (`docs/PREENREGISTREMENT_5USD_V2.md`), fixees AVANT mesure.
K_PAR_JAMBE = 3
FENETRE_H = 96

MOTIF_PAS_ASSEZ = "PAS_ASSEZ_DE_COINS_CLASSABLES"
MOTIF_SOUS_MINIMUM = "JAMBE_SOUS_LE_NOTIONNEL_MINIMUM"


@dataclass(frozen=True, slots=True)
class Refus:
    """Pourquoi aucune proposition. Un refus explicite vaut mieux qu'un livre tronque."""

    motif: str
    detail: str = ""


def moyenne_anterieure(serie: Mapping[int, float], *, fin_exclue: int,
                       fenetre_h: int) -> float | None:
    """Moyenne du funding sur `[fin_exclue - fenetre, fin_exclue)` — **borne haute EXCLUE**.

    L'exclusion est la frontiere entre une mesure et un lookahead : inclure l'heure de decision
    ferait entrer dans le classement une information qu'on n'avait pas au moment de decider.
    `None` quand la fenetre est vide — et surtout pas 0,0, qui serait un classement (« funding
    nul ») au lieu d'une absence de classement.
    """
    debut = int(fin_exclue) - int(fenetre_h)
    valeurs = [float(v) for h, v in serie.items()
               if debut <= h < int(fin_exclue) and isinstance(v, (int, float))]
    return (sum(valeurs) / len(valeurs)) if valeurs else None


class CarryTransversalInverse:
    """Le livre : `k` longs sur le funding le plus haut, `k` shorts sur le plus bas."""

    kind = StrategyKind.SPREAD_FARM

    def __init__(self, definition):
        self.definition = definition

    @property
    def strategy_id(self) -> str:
        return self.definition.strategy_id

    @classmethod
    def default(cls) -> "CarryTransversalInverse":
        return cls(make_strategy(
            strategy_id="carry_transversal_inverse", version=1, kind=cls.kind,
            name="Carry transversal INVERSE (long funding haut)",
            params={"k_par_jambe": K_PAR_JAMBE, "fenetre_h": FENETRE_H}))

    def classer(self, funding: Mapping[str, Mapping[int, float]], *, instant_h: int,
                fenetre_h: int | None = None,
                k: int | None = None) -> tuple[list[str], list[str]] | Refus:
        """`(longs, shorts)` — le haut et le bas du classement. Causal par construction."""
        fenetre = int(fenetre_h if fenetre_h is not None else self._p("fenetre_h", FENETRE_H))
        k_eff = int(k if k is not None else self._p("k_par_jambe", K_PAR_JAMBE))
        classables: list[tuple[float, str]] = []
        for coin, serie in funding.items():
            moyenne = moyenne_anterieure(serie, fin_exclue=instant_h, fenetre_h=fenetre)
            if moyenne is not None:
                classables.append((moyenne, str(coin)))
        if len(classables) < 2 * k_eff:
            return Refus(MOTIF_PAS_ASSEZ,
                         f"{len(classables)} classables, il en faut {2 * k_eff}")
        classables.sort(reverse=True)
        return ([c for _, c in classables[:k_eff]],      # funding le plus HAUT -> on LONGE
                [c for _, c in classables[-k_eff:]])     # le plus BAS -> on SHORTE

    def proposer(self, funding: Mapping[str, Mapping[int, float]], *, instant_h: int,
                 notionnel_total_usd: float, context: RunContext = RunContext.LIVE,
                 now_ms: int = 0, fenetre_h: int | None = None,
                 k: int | None = None) -> tuple[PaperIntent, ...] | Refus:
        """Les intentions du livre, ou un REFUS motive. Jamais un livre partiel."""
        classement = self.classer(funding, instant_h=instant_h, fenetre_h=fenetre_h, k=k)
        if isinstance(classement, Refus):
            return classement
        longs, shorts = classement
        jambes = len(longs) + len(shorts)
        par_jambe = float(notionnel_total_usd) / jambes if jambes else 0.0
        if par_jambe < NOTIONNEL_MINIMUM_USD:
            # Proposer un livre non placable serait proposer un livre qui n'existera pas.
            return Refus(MOTIF_SOUS_MINIMUM,
                         f"{par_jambe:.2f} USD par jambe sur {jambes}, minimum "
                         f"{NOTIONNEL_MINIMUM_USD:.0f} USD : il faut au moins "
                         f"{jambes * NOTIONNEL_MINIMUM_USD:.0f} USD de notionnel")
        motifs = ("ENCOMBREMENT_DU_POSITIONNEMENT", "LIVRE_DOLLAR_NEUTRE",
                  "SENS_INVERSE_DU_CARRY")
        intentions: list[PaperIntent] = []
        for coin, side in [(c, IntentSide.LONG) for c in longs] + \
                          [(c, IntentSide.SHORT) for c in shorts]:
            intentions.append(PaperIntent(
                strategy_id=self.strategy_id, coin=str(coin).upper(), side=side,
                action=IntentAction.OPEN, target_notional_usdt=par_jambe,
                # La confiance n'est PAS une probabilite de gain : 58 % des detentions mesurees
                # sont positives, l'edge vient de l'ASYMETRIE. On ne surjoue pas ce chiffre.
                confidence=0.58, context=context, reasons=motifs, created_at_ms=int(now_ms)))
        return tuple(intentions)

    def _p(self, cle: str, defaut: Any) -> Any:
        return self.definition.params.get(cle, defaut)


__all__ = ["CarryTransversalInverse", "Refus", "moyenne_anterieure",
           "NOTIONNEL_MINIMUM_USD", "K_PAR_JAMBE", "FENETRE_H",
           "MOTIF_PAS_ASSEZ", "MOTIF_SOUS_MINIMUM"]
