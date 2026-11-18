"""UN ENSEMBLE D'IDENTITÉS QUI TIENT EN MÉMOIRE, pour dédupliquer des dizaines de millions de lignes.

POURQUOI CE MODULE EXISTE. Le 18/11/2026, un scellement du coffre a atteint **9,13 Go** et fait
tomber la machine à 1,8 Go de RAM libre — assez pour menacer les collecteurs de l'opérateur, qui
tournaient depuis 21 heures. La cause tenait en une ligne : le scelleur garde un `set` de **tuples**
d'identité, et pour les fills ce tuple contient un `hash` de transaction de 66 caractères.

Mesure sur 300 000 entrées, extrapolée aux 27 544 473 lignes de fills du coffre :

| forme                         | octets/entrée | pour 27,5 M |
|-------------------------------|---------------|-------------|
| tuple + hash 66 c (l'ancien)  |         294,6 |    8,12 Go  |
| `bytes` de 16 octets          |          77,0 |    2,12 Go  |
| **deux `array('Q')` triés**   |      **16,2** | **0,45 Go** |

Le gain ne vient pas de l'empreinte seule mais de l'**absence de conteneur par élément** : un `set`
Python coûte une soixantaine d'octets par entrée en plus de l'objet qu'il range.

CE QUI EST GARANTI, et pourquoi l'empreinte courte est écartée :

* l'empreinte fait **128 bits** (`blake2b`, 16 octets). À 27,5 millions d'entrées, la probabilité
  d'une collision est de l'ordre de 10⁻²³. Une empreinte de 64 bits aurait suffi en mémoire — et
  donné une collision tous les ~50 000 scellements, c'est-à-dire une ligne neuve prise pour un
  doublon et **écartée en silence**. Perdre une donnée pour économiser huit octets est exactement
  l'échange que ce dépôt refuse partout ailleurs ;
* l'identité d'origine est sérialisée de façon **déterministe** avant d'être hachée : deux
  exécutions donnent la même empreinte, donc une reprise retrouve ses doublons ;
* la structure est hybride : un `set` **tampon** absorbe les ajouts récents, et deux `array('Q')`
  **triés** portent la masse. Chercher consulte le tampon puis les tableaux par recherche binaire.
  Quand le tampon dépasse `TAMPON_MAX`, il est fusionné — opération rare, coût amorti.
"""
from __future__ import annotations

import bisect
import hashlib
from array import array
from collections.abc import Iterable
from typing import Any

#: Taille de l'empreinte. 16 octets = 128 bits : voir l'avertissement sur les 64 bits en tête.
OCTETS_EMPREINTE = 16

#: Au-delà, le tampon est fusionné dans les tableaux triés. Assez grand pour que la fusion soit
#: rare, assez petit pour que la recherche linéaire dans le tampon reste négligeable.
TAMPON_MAX = 50_000


def empreinte(cle: Any) -> tuple[int, int]:
    """Les 128 bits d'une identité, en deux entiers de 64 bits.

    La sérialisation passe par `repr`, qui est déterministe pour les tuples de chaînes, d'entiers et
    de `None` — la forme que produit `coffre_certifie.identite`. Deux exécutions donnent donc la
    même empreinte, ce dont dépend toute reprise.
    """
    brut = hashlib.blake2b(repr(cle).encode("utf-8"), digest_size=OCTETS_EMPREINTE).digest()
    return int.from_bytes(brut[:8], "big"), int.from_bytes(brut[8:], "big")


class EnsembleDIdentites:
    """Un ensemble d'identités compact, qui répond à ``in`` et ``add`` comme un `set`.

    Il se substitue à un `set` de tuples là où les volumes dépassent le million d'entrées. Pour de
    petits volumes, un `set` ordinaire reste plus simple et plus rapide : ce conteneur n'existe que
    parce que 27,5 millions de tuples coûtaient 8 Go.
    """

    __slots__ = ("_hauts", "_bas", "_tampon", "_fusions")

    def __init__(self, identites: Iterable[Any] = ()) -> None:
        self._hauts = array("Q")
        self._bas = array("Q")
        self._tampon: set[tuple[int, int]] = set()
        self._fusions = 0
        for identite in identites:
            self.add(identite)

    # ───────────────────────── l'interface d'un `set` ─────────────────────────

    def add(self, identite: Any) -> None:
        paire = empreinte(identite)
        if paire in self._tampon or self._dans_les_tableaux(paire):
            return
        self._tampon.add(paire)
        if len(self._tampon) >= TAMPON_MAX:
            self._fusionner()

    def __contains__(self, identite: Any) -> bool:
        paire = empreinte(identite)
        return paire in self._tampon or self._dans_les_tableaux(paire)

    def __len__(self) -> int:
        return len(self._hauts) + len(self._tampon)

    # ───────────────────────── la mécanique ─────────────────────────

    def _dans_les_tableaux(self, paire: tuple[int, int]) -> bool:
        """Recherche binaire sur le haut, puis balayage des quelques doublons de haut.

        Deux empreintes partageant leurs 64 bits de poids fort sont rarissimes ; quand cela arrive,
        on compare les 64 bits de poids faible, et la réponse reste exacte.
        """
        haut, bas = paire
        gauche = bisect.bisect_left(self._hauts, haut)
        for rang in range(gauche, len(self._hauts)):
            if self._hauts[rang] != haut:
                return False
            if self._bas[rang] == bas:
                return True
        return False

    def _fusionner(self) -> None:
        """Verse le tampon dans les tableaux triés, SANS matérialiser de liste de tuples.

        La première version faisait `sorted(list(zip(hauts, bas)) + sorted(tampon))`. Au moment de
        la fusion, le pic redevenait celui qu'on voulait éviter — 8,41 Mo contre 12,79 pour un `set`
        ordinaire, soit un gain de 1,5 au lieu de 18. Un conteneur compact dont la maintenance coûte
        aussi cher que la forme qu'il remplace n'économise rien, et le test de mémoire l'a refusé.

        Ici, deux sources triées sont fusionnées à deux index directement dans de nouveaux
        tableaux : le pic vaut les anciens plus les nouveaux, soit 32 octets par entrée.
        """
        if not self._tampon:
            return
        ajout = sorted(self._tampon)          # petit : au plus TAMPON_MAX entrées
        hauts, bas = array("Q"), array("Q")
        i = j = 0
        n_anciens, n_ajout = len(self._hauts), len(ajout)
        while i < n_anciens and j < n_ajout:
            ancien = (self._hauts[i], self._bas[i])
            if ancien <= ajout[j]:
                hauts.append(ancien[0]); bas.append(ancien[1]); i += 1
            else:
                hauts.append(ajout[j][0]); bas.append(ajout[j][1]); j += 1
        while i < n_anciens:
            hauts.append(self._hauts[i]); bas.append(self._bas[i]); i += 1
        while j < n_ajout:
            hauts.append(ajout[j][0]); bas.append(ajout[j][1]); j += 1
        self._hauts, self._bas = hauts, bas
        self._tampon.clear()
        self._fusions += 1

    # ───────────────────────── ce qu'il publie de lui-même ─────────────────────────

    def bilan(self) -> dict[str, int]:
        """De quoi écrire dans un rapport ce que cet ensemble a coûté et fait."""
        self._fusionner()
        return {
            "identites": len(self._hauts),
            "fusions": self._fusions,
            "octets_approximatifs": len(self._hauts) * 16,
        }


__all__ = ["OCTETS_EMPREINTE", "TAMPON_MAX", "empreinte", "EnsembleDIdentites"]
