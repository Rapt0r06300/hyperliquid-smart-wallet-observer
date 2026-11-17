"""Sauts de l'horloge murale, détectés contre l'horloge monotone portée par chaque fill.

POURQUOI. Toute la causalité du Copy-Vault repose sur un ordre : « ce carnet a été REÇU avant ce
signal ». Cet ordre est lu sur l'horloge murale (`received_at_ms`). Si Windows recule l'heure de
`d` millisecondes, un carnet reçu APRÈS un signal peut porter un horodatage ANTÉRIEUR au sien,
pendant `d` millisecondes : une référence « pré-signal » qui n'en est pas une.

Le 17/11/2026, après une mise en veille du PC, Windows a recalé l'heure de +1,24 s. Un saut en
avant conserve l'ordre — mais rien ne détectait un saut en arrière. Chaque fill porte pourtant une
horloge monotone (`recv_mono_ns`) : l'écart entre les deux horloges est constant tant que l'heure
murale n'est pas touchée. Mesure sur tout le ruban (92 694 fills, 44 h) : un seul saut, celui du
réveil (+1 195 ms), aucun en arrière.

Ce module ne répare rien : il DÉTECTE, il nomme la fenêtre ambiguë, et il compte les signaux qui
y tombent. Un rapport sans ligne monotone ne dit pas « aucun saut » : il dit `NON_MESURABLE`.
"""
from __future__ import annotations

from collections import deque
from typing import Any

#: En dessous, c'est la gigue normale entre deux lectures d'horloge.
SEUIL_MS = 100
#: Garde autour d'une fenêtre ambiguë.
MARGE_MS = 250
#: Un « recul » de plus d'une heure n'est pas une correction d'heure : ce sont des lignes de deux
#: démarrages de la machine lues dans le désordre (l'horloge monotone repart de zéro au démarrage).
RECUL_PLAUSIBLE_MAX_MS = 3_600_000
#: Signaux récents gardés en mémoire pour compter ceux qu'un saut rend suspects après coup.
MEMOIRE_SIGNAUX_MS = 120_000

VERDICT_OK = "OK"
VERDICT_AMBIGU = "HORLOGE_AMBIGUE"
VERDICT_NON_MESURABLE = "NON_MESURABLE"


class Detecteur:
    """Observe des lignes une à une ; l'ordre de lecture n'a pas besoin d'être l'ordre de réception.

    L'écart ``murale − monotone`` ne dépend pas de l'ordre : deux lignes lues dans le désordre
    reculent des deux horloges à la fois.
    """

    def __init__(self, *, seuil_ms: int = SEUIL_MS, marge_ms: int = MARGE_MS,
                 max_exemples: int = 20) -> None:
        self.seuil_ms = int(seuil_ms)
        self.marge_ms = int(marge_ms)
        self.max_exemples = int(max_exemples)
        self.lignes = 0
        self.sans_monotone = 0
        self.n_avant = 0
        self.n_arriere = 0
        self.n_redemarrages = 0
        self.plus_grand_recul_ms = 0
        self.avant: list[dict[str, int]] = []
        self.arriere: list[dict[str, int]] = []
        self.fenetres: list[tuple[int, int]] = []
        self.signaux_refuses = 0
        self.signaux_deja_juges = 0
        self._decalage: float | None = None
        self._dernier_recu: int | None = None
        self._signaux: deque[int] = deque()

    def observer(self, recu_ms: Any, mono_ns: Any) -> None:
        if type(recu_ms) is not int or type(mono_ns) is not int:
            self.sans_monotone += 1
            return
        self.lignes += 1
        decalage = recu_ms - mono_ns / 1e6
        if self._decalage is not None and self._dernier_recu is not None:
            ecart = decalage - self._decalage
            if ecart > self.seuil_ms:
                self.n_avant += 1
                if len(self.avant) < self.max_exemples:
                    self.avant.append({"avant_ms": self._dernier_recu, "apres_ms": recu_ms,
                                       "saut_ms": round(ecart)})
            elif ecart < -self.seuil_ms:
                recul = -ecart
                if recul > RECUL_PLAUSIBLE_MAX_MS:
                    self.n_redemarrages += 1
                else:
                    self._noter_recul(recu_ms, recul)
        self._decalage = decalage
        self._dernier_recu = recu_ms

    def _noter_recul(self, recu_ms: int, recul: float) -> None:
        assert self._dernier_recu is not None
        self.n_arriere += 1
        self.plus_grand_recul_ms = max(self.plus_grand_recul_ms, round(recul))
        debut = min(recu_ms, self._dernier_recu) - round(recul) - self.marge_ms
        fin = max(recu_ms, self._dernier_recu) + self.marge_ms
        self.fenetres.append((debut, fin))
        self.signaux_deja_juges += sum(1 for s in self._signaux if debut <= s <= fin)
        if len(self.arriere) < self.max_exemples:
            self.arriere.append({"avant_ms": self._dernier_recu, "apres_ms": recu_ms,
                                 "recul_ms": round(recul), "fenetre_debut_ms": debut,
                                 "fenetre_fin_ms": fin})

    def ambigu(self, recu_ms: Any) -> bool:
        """Cet horodatage tombe-t-il dans une fenêtre où l'ordre de réception n'est plus sûr ?"""
        if type(recu_ms) is not int:
            return False
        return any(debut <= recu_ms <= fin for debut, fin in self.fenetres)

    def noter_signal(self, recu_ms: int, *, refuse: bool = False) -> None:
        """Mémorise un signal jugé, pour pouvoir le compter si un saut le rend suspect ensuite."""
        if refuse:
            self.signaux_refuses += 1
            return
        self._signaux.append(recu_ms)
        while self._signaux and recu_ms - self._signaux[0] > MEMOIRE_SIGNAUX_MS:
            self._signaux.popleft()

    def bilan(self) -> dict[str, Any]:
        if not self.lignes:
            verdict = VERDICT_NON_MESURABLE
        elif self.n_arriere:
            verdict = VERDICT_AMBIGU
        else:
            verdict = VERDICT_OK
        return {
            "verdict": verdict,
            "lignes_avec_horloge_monotone": self.lignes,
            "lignes_sans_horloge_monotone": self.sans_monotone,
            "sauts_en_avant": self.n_avant,
            "sauts_en_arriere": self.n_arriere,
            "plus_grand_recul_ms": self.plus_grand_recul_ms,
            "redemarrages_lus_dans_le_desordre": self.n_redemarrages,
            "signaux_refuses_dans_une_fenetre": self.signaux_refuses,
            "signaux_deja_juges_dans_une_fenetre": self.signaux_deja_juges,
            "exemples_en_avant": list(self.avant),
            "exemples_en_arriere": list(self.arriere),
            "seuil_ms": self.seuil_ms,
        }


__all__ = ["SEUIL_MS", "MARGE_MS", "RECUL_PLAUSIBLE_MAX_MS", "MEMOIRE_SIGNAUX_MS", "VERDICT_OK",
           "VERDICT_AMBIGU", "VERDICT_NON_MESURABLE", "Detecteur"]
