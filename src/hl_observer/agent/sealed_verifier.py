"""LE GENERATEUR NE NOTE JAMAIS SON PROPRE TRAVAIL (2026-07-12).

    « An agent that grades its own output sees its own reasoning and prefers conclusions
      consistent with what it already built. In trading this failure mode has a price tag:
      a loop that memorizes one dataset looks like improvement on the chart and behaves like
      a coin flip live. »

ON A DEJA PAYE CE PRIX. Le replay de 150 millions de scenarios a trouve des configurations
splendides sur le train. Elles sont mortes sur le holdout : `robust_count = 0`.

La boucle avait raison. C'est nous qui aurions pu nous mentir -- si le gate n'avait pas tenu.

CE MODULE SCELLE LE HOLDOUT.

Aujourd'hui, rien n'EMPECHE de selectionner sur le holdout : c'est une convention, une discipline,
une bonne intention. Les bonnes intentions ne survivent pas a une session de 3 h ou l'on veut
desesperement un chiffre positif.

    * le holdout est SCELLE. On ne peut pas le lire pendant la selection ;
    * il ne s'ouvre qu'UNE FOIS, pour UN candidat, et l'ouverture est TRACEE ;
    * une deuxieme ouverture est REFUSEE -- si on regarde le holdout deux fois, on le
      selectionne, et il n'est plus un holdout : c'est du train qui s'ignore ;
    * une variante ne survit que si elle gagne sur les DEUX tranches.

C'est la difference entre une science et une seance de voyance avec des decimales.

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from hl_observer.agent.fitness import Fitness, evaluer

MOTIF_DEJA_OUVERT = "HOLDOUT_DEJA_CONSOMME"
MOTIF_ECHEC_TRAIN = "REJETE_SUR_TRAIN"
MOTIF_ECHEC_VALIDATION = "REJETE_SUR_VALIDATION"
MOTIF_ECHEC_HOLDOUT = "REJETE_SUR_HOLDOUT_MIRAGE_DU_TRAIN"
MOTIF_SCELLE = "HOLDOUT_SCELLE_PENDANT_LA_SELECTION"


class HoldoutViole(RuntimeError):
    """On a essaye de regarder le holdout pendant la selection. C'est de la triche."""


@dataclass(slots=True)
class Verdict:
    candidat: str
    train: Fitness | None
    validation: Fitness | None
    holdout: Fitness | None
    promu: bool
    motifs: tuple[str, ...]
    ouverture_holdout: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidat": self.candidat,
            "train": self.train.as_dict() if self.train else None,
            "validation": self.validation.as_dict() if self.validation else None,
            "holdout": self.holdout.as_dict() if self.holdout else None,
            "promu": self.promu,
            "motifs": list(self.motifs),
            "ouverture_holdout": self.ouverture_holdout,
            "regle": "une variante ne survit que si elle gagne sur train ET validation ET holdout",
            "real_execution": False,
        }


@dataclass(slots=True)
class VerificateurScelle:
    """Le holdout, sous scelle. Il ne s'ouvre qu'une fois, et l'ouverture laisse une trace."""

    _holdout: Sequence[float] = field(default_factory=tuple, repr=False)
    _fenetres_holdout: Sequence[Sequence[float]] | None = field(default=None, repr=False)
    _ouvert: bool = False
    _ouvert_pour: str = ""
    _ouvert_le: str = ""
    journal: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ le scelle

    @property
    def scelle(self) -> bool:
        return not self._ouvert

    def lire_holdout_pendant_selection(self) -> None:
        """Appeler ceci LEVE. C'est le point : le holdout est INACCESSIBLE a la selection."""
        raise HoldoutViole(
            "Le holdout est scelle pendant la selection. Le regarder, c'est le selectionner -- "
            "et il n'est alors plus un holdout, c'est du train qui s'ignore."
        )

    # ------------------------------------------------------------------ le verdict

    def juger(
        self,
        candidat: str,
        *,
        train: Sequence[float],
        validation: Sequence[float],
        fenetres_train: Sequence[Sequence[float]] | None = None,
        fenetres_validation: Sequence[Sequence[float]] | None = None,
    ) -> Verdict:
        """Le verdict complet. Le holdout n'est ouvert QUE si train ET validation passent.

        C'est economique autant qu'honnete : on ne brule pas le holdout sur un candidat qui a
        deja echoue avant.
        """
        f_train = evaluer(train, fenetres=fenetres_train)
        if not f_train.accepte:
            return Verdict(candidat, f_train, None, None, False,
                           (MOTIF_ECHEC_TRAIN, *f_train.motifs_de_rejet))

        f_val = evaluer(validation, fenetres=fenetres_validation)
        if not f_val.accepte:
            return Verdict(candidat, f_train, f_val, None, False,
                           (MOTIF_ECHEC_VALIDATION, *f_val.motifs_de_rejet))

        # --- le holdout ne s'ouvre qu'UNE fois, et jamais deux
        if self._ouvert:
            return Verdict(
                candidat, f_train, f_val, None, False,
                (MOTIF_DEJA_OUVERT,),
                ouverture_holdout="deja ouvert le %s pour '%s'" % (self._ouvert_le, self._ouvert_pour),
            )

        self._ouvert = True
        self._ouvert_pour = candidat
        self._ouvert_le = datetime.now(timezone.utc).isoformat(timespec="seconds")

        f_hold = evaluer(self._holdout, fenetres=self._fenetres_holdout)
        promu = f_hold.accepte

        v = Verdict(
            candidat, f_train, f_val, f_hold, promu,
            () if promu else (MOTIF_ECHEC_HOLDOUT, *f_hold.motifs_de_rejet),
            ouverture_holdout="ouvert le %s pour '%s' -- UNIQUE ET DEFINITIF"
                              % (self._ouvert_le, candidat),
        )
        self.journal.append(v.as_dict())
        return v

    def sceller_a_nouveau(self, *, nouveau_holdout: Sequence[float], raison: str) -> None:
        """On ne re-scelle QUE sur des donnees NEUVES, jamais vues. Et on dit pourquoi.

        Re-sceller sur les memes donnees serait un mensonge : elles ont deja parle une fois.
        """
        if not str(raison).strip():
            raise HoldoutViole("on ne re-scelle pas un holdout sans raison ecrite")
        if not nouveau_holdout:
            raise HoldoutViole("un holdout vide ne prouve rien")
        self._holdout = tuple(nouveau_holdout)
        self._ouvert = False
        self._ouvert_pour = ""
        self._ouvert_le = ""


def selectionner(
    candidats: Sequence[str],
    *,
    noter: Callable[[str], tuple[Sequence[float], Sequence[Sequence[float]]]],
) -> tuple[str, Fitness] | None:
    """La selection tourne SANS JAMAIS voir le holdout. C'est tout l'interet.

    `noter` rend (pnls, fenetres) sur train+validation UNIQUEMENT.
    """
    meilleur: tuple[str, Fitness] | None = None
    for c in candidats:
        pnls, fenetres = noter(c)
        f = evaluer(pnls, fenetres=fenetres)
        if not f.accepte:
            continue
        if meilleur is None or f.score > meilleur[1].score:
            meilleur = (c, f)
    return meilleur


__all__ = [
    "MOTIF_DEJA_OUVERT", "MOTIF_ECHEC_HOLDOUT", "MOTIF_ECHEC_TRAIN", "MOTIF_ECHEC_VALIDATION",
    "MOTIF_SCELLE",
    "HoldoutViole", "Verdict", "VerificateurScelle", "selectionner",
]
