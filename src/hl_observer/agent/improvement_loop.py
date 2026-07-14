"""LA BOUCLE : generer -> evaluer -> noter -> selectionner, AVEC MEMOIRE (2026-07-12).

Le framework, reproduit en entier -- et honnetement.

    generateur  -> propose des variantes
    CIMETIERE   -> refuse celles qui tombent dans une zone deja morte   <-- la piece qui manquait
    evaluateur  -> les note sur train + validation (JAMAIS le holdout)
    selecteur   -> garde la meilleure
    verificateur SCELLE -> ouvre le holdout UNE fois, pour UN candidat
    memoire     -> enterre l'echec avec sa preuve chiffree

CE QUE CETTE BOUCLE NE FERA PAS, ET IL FAUT LE DIRE :

    ELLE NE CREERA PAS UN EDGE QUI N'EXISTE PAS.

AlphaEvolve a trouve un algorithme de multiplication matricielle plus rapide parce qu'un tel
algorithme EXISTE -- c'est un objet mathematique qui attendait d'etre trouve. Aucun theoreme ne
garantit qu'une configuration de copy-trading rentable existe dans les donnees d'Hyperliquid.

On a deja fouille 150 MILLIONS de points de cet espace avec exactement cette boucle.
Reponse : `robust_count = 0`. La boucle a parfaitement fonctionne. C'est l'espace qui est vide.

Une boucle de recherche est un outil pour TROUVER, pas pour FAIRE EXISTER. Sa vraie valeur ici
n'est pas de nous rendre riches : c'est de nous empecher de nous mentir, et de ne jamais
re-payer une impasse deja payee.

PUR (le generateur et l'evaluateur sont injectes). Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from hl_observer.agent.dead_zones import RegistreZonesMortes, creer_zone_morte
from hl_observer.agent.fitness import Fitness, evaluer
from hl_observer.agent.sealed_verifier import VerificateurScelle, Verdict

MOTIF_ZONE_MORTE = "PROPOSITION_DANS_UNE_ZONE_MORTE"


@dataclass(slots=True)
class Iteration:
    proposition: str
    refuse_par_memoire: str          # non vide = on a economise un backtest
    fitness: Fitness | None
    retenu: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposition": self.proposition,
            "refuse_par_memoire": self.refuse_par_memoire,
            "fitness": self.fitness.as_dict() if self.fitness else None,
            "retenu": self.retenu,
        }


@dataclass(slots=True)
class RapportBoucle:
    iterations: list[Iteration] = field(default_factory=list)
    economisees_par_memoire: int = 0
    evaluees: int = 0
    candidats_retenus: int = 0
    verdict_final: Verdict | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "iterations": [i.as_dict() for i in self.iterations],
            "economisees_par_memoire": self.economisees_par_memoire,
            "evaluees": self.evaluees,
            "candidats_retenus": self.candidats_retenus,
            "verdict_final": self.verdict_final.as_dict() if self.verdict_final else None,
            "avertissement": (
                "Une boucle de recherche ne CREE pas un edge. Elle le trouve s'il existe. "
                "150 millions de scenarios ont deja rendu robust_count = 0 : l'espace du "
                "copy-trading est vide. Chercher plus fort n'y changera rien."
            ),
            "real_execution": False,
        }


class BoucleAmelioration:
    """generer -> consulter la memoire -> evaluer -> selectionner -> enterrer l'echec."""

    def __init__(
        self,
        *,
        registre: RegistreZonesMortes,
        verificateur: VerificateurScelle,
        evaluer_sur_train: Callable[[str], tuple[Sequence[float], Sequence[Sequence[float]]]],
        evaluer_sur_validation: Callable[[str], tuple[Sequence[float], Sequence[Sequence[float]]]],
    ) -> None:
        self.registre = registre
        self.verificateur = verificateur
        self._train = evaluer_sur_train
        self._validation = evaluer_sur_validation

    def tourner(self, propositions: Sequence[str]) -> RapportBoucle:
        rapport = RapportBoucle()
        meilleur: tuple[str, Fitness] | None = None

        for prop in propositions:
            # 1) CONSULT -- la piece qui manquait. On ne re-paie pas une impasse deja payee.
            refus = self.registre.refus(prop)
            if refus:
                rapport.iterations.append(Iteration(prop, refus, None, False))
                rapport.economisees_par_memoire += 1
                continue

            # 2) EVALUER -- sur train uniquement. Le holdout reste SCELLE.
            pnls, fenetres = self._train(prop)
            f = evaluer(pnls, fenetres=fenetres)
            rapport.evaluees += 1
            rapport.iterations.append(Iteration(prop, "", f, f.accepte))
            if not f.accepte:
                continue

            rapport.candidats_retenus += 1
            if meilleur is None or f.score > meilleur[1].score:
                meilleur = (prop, f)

        # 3) VERIFIER -- le holdout ne s'ouvre que maintenant, une seule fois.
        if meilleur is not None:
            train_pnls, train_fen = self._train(meilleur[0])
            val_pnls, val_fen = self._validation(meilleur[0])
            rapport.verdict_final = self.verificateur.juger(
                meilleur[0],
                train=train_pnls, validation=val_pnls,
                fenetres_train=train_fen, fenetres_validation=val_fen,
            )

        return rapport

    # ------------------------------------------------------------------ distil

    def enterrer_lechec(
        self,
        *,
        id: str,
        hypothese: str,
        verdict: str,
        mesure: str,
        valeur: float,
        unite: str,
        echantillon: int,
        lecon: str,
        condition_de_reouverture: str,
        entree_mesuree: str,
        mots_cles: Sequence[str] = (),
    ) -> bool:
        """`distil` : transformer un echec en REGLE GENERALE, pas en anecdote.

        Sans cette etape, la boucle re-propose eternellement ce qu'elle a deja rejete.

        🔴 `entree_mesuree` est OBLIGATOIRE depuis le 2026-07-13 : une zone morte qui ne dit pas
        sur QUELLE ENTREE elle a mesure refuserait des idees dont elle ne parle pas. C'est la
        faute exacte que j'ai commise sur IDEA-04 et IDEA-47.
        """
        z = creer_zone_morte(
            id=id, hypothese=hypothese, verdict=verdict, mesure=mesure, valeur=valeur,
            unite=unite, echantillon=echantillon, lecon=lecon,
            condition_de_reouverture=condition_de_reouverture,
            entree_mesuree=entree_mesuree, mots_cles=mots_cles,
        )
        return self.registre.enterrer(z)


__all__ = ["MOTIF_ZONE_MORTE", "BoucleAmelioration", "Iteration", "RapportBoucle"]
