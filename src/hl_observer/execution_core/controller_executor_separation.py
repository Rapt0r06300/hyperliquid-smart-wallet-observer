"""[ALL #86] CONTROLLER/EXECUTOR SEPARATION : les modules DÉTECTENT des opportunités (Controller, sans état de
position) ; un EXECUTOR dédié possède TOUTE la responsabilité du cycle de vie économique (position, PnL, sortie).
Architecture Strategy V2 (Hummingbot). Un controller qui gérerait lui-même des positions mélangerait détection et
exécution — bug de conception. Ici on sépare et on vérifie l'invariant. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class Controller:
    """Détecte des candidats. NE possède AUCUN état de position ni de cycle de vie (données seulement)."""

    def __init__(self) -> None:
        self._compteur = 0

    def detecter(self, opportunites: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transforme des opportunités en CANDIDATS purs (dict), sans ouvrir ni suivre quoi que ce soit."""
        out = []
        for o in opportunites:
            self._compteur += 1
            out.append({"candidat_id": "cand_%d" % self._compteur, "signal": dict(o), "possede_position": False})
        return out


class Executor:
    """Prend en charge un candidat et possède SON cycle de vie économique (position, réalisé)."""

    def __init__(self, candidat: dict[str, Any]) -> None:
        self.candidat = dict(candidat)
        self.position = 0.0
        self.realized = 0.0
        self.etat = "RUNNING"

    def prendre_en_charge(self, taille: float) -> None:
        self.position = float(taille)


def controller_sans_etat(c: Controller) -> bool:
    """Invariant : un Controller n'expose aucun attribut de position/cycle de vie (c'est le rôle de l'Executor)."""
    interdits = ("position", "realized", "etat")
    return not any(hasattr(c, a) for a in interdits)


__all__ = ["Controller", "Executor", "controller_sans_etat"]
