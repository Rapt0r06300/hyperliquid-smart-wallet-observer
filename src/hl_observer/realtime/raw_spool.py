"""#501 + #502 — LE RAW SPOOL et « UN CONSOMMATEUR LENT NE DOIT JAMAIS BLOQUER LA SOCKET ».

═══════════════════════════════════════════════════════════════════════════════════════════════
LES DEUX RÈGLES, ET POURQUOI ELLES SONT LIÉES
═══════════════════════════════════════════════════════════════════════════════════════════════

**#501 — ÉCRIRE LA TRAME BRUTE AVANT DE LA PARSER.**

    ***Si on parse mal, on perd la donnée POUR TOUJOURS.***

Le parseur peut changer, avoir un bug, ignorer un champ qu'on découvrira utile dans six mois
(*`liquidationPx` était REÇU et EFFACÉ pendant des semaines*). La trame brute, elle, est la
vérité. **On l'écrit d'abord, on la parse ensuite.** Le disque est bon marché ; un mois de
collecte perdu ne l'est pas.

**#502 — UN CONSOMMATEUR LENT NE DOIT JAMAIS BLOQUER LA SOCKET.**

Si le code qui traite les messages est plus lent que le flux, deux issues :
  * ou bien la file grandit sans fin -> **la mémoire explose** (on a déjà eu un crash de DB) ;
  * ou bien on `await` sur un consommateur lent -> **la socket cesse de lire** -> le serveur
    coupe, ou les messages s'empilent côté OS.

🔴 ***C'est très probablement la cause des STALLS à 02:32 et 04:08.*** Le flux s'arrêtait, et
`signal_age` — qui était une tautologie — **gelait** au lieu de crier. **Deux bugs qui se
cachaient l'un l'autre.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LA SOLUTION : SÉPARER LA LECTURE DU TRAITEMENT
═══════════════════════════════════════════════════════════════════════════════════════════════

    socket ──► [spool brut sur disque]  (rapide, jamais bloquant)
            └► [file BORNÉE] ──► consommateur (lent, sans importance)

  * La file est **bornée**. Quand elle est pleine, on **JETTE** — et **on COMPTE ce qu'on a
    jeté**. *Une perte silencieuse est un mensonge ; une perte comptée est une mesure.*
  * On jette le **PLUS ANCIEN** (le marché ne s'intéresse pas à un carnet d'il y a 3 minutes),
    **jamais le plus récent**.
  * La trame brute, elle, est **déjà sur disque** : même jetée de la file, elle n'est pas perdue.

***La donnée brute est sacrée. Le traitement est jetable.***

PUR : aucun réseau ici. Aucun ordre réel.
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# Une file bornée. Au-delà, on jette le plus ANCIEN et on le compte.
TAILLE_FILE_PAR_DEFAUT = 10_000

# Au-delà, un message est trop vieux pour valoir un traitement.
AGE_MAX_MS = 5_000

MOTIF_FILE_PLEINE = "FILE_PLEINE_MESSAGE_LE_PLUS_ANCIEN_JETE"
MOTIF_TROP_VIEUX = "MESSAGE_TROP_VIEUX_JETE_AVANT_TRAITEMENT"


@dataclass(slots=True)
class Compteurs:
    """🔴 **Ce qui est jeté doit être COMPTÉ.** Une perte silencieuse est un mensonge."""
    recus: int = 0
    spooles: int = 0
    traites: int = 0
    jetes_file_pleine: int = 0
    jetes_trop_vieux: int = 0
    erreurs_de_parse: int = 0

    @property
    def perdus(self) -> int:
        return self.jetes_file_pleine + self.jetes_trop_vieux

    @property
    def taux_de_perte(self) -> float:
        return (self.perdus / self.recus) if self.recus else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "recus": self.recus, "spooles": self.spooles, "traites": self.traites,
            "jetes_file_pleine": self.jetes_file_pleine,
            "jetes_trop_vieux": self.jetes_trop_vieux,
            "erreurs_de_parse": self.erreurs_de_parse,
            "perdus": self.perdus,
            "taux_de_perte": round(self.taux_de_perte, 6),
            "note": ("Les messages JETES de la file restent **sur le spool brut** : ils ne sont "
                     "PAS perdus, seulement non traites en temps reel. "
                     "*La donnee brute est sacree ; le traitement est jetable.*"),
            "real_execution": False,
        }


class RawSpool:
    """#501 — La trame BRUTE, écrite AVANT tout parsing.

    *Si on parse mal, on perd la donnée pour toujours.* Le spool, lui, ne juge pas.
    """

    def __init__(self, chemin: Path | str, *, flush_tous_les: int = 50) -> None:
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.chemin.open("a", encoding="utf-8")
        self._flush_tous_les = max(1, int(flush_tous_les))
        self._depuis_flush = 0

    def ecrire(self, brut: str, *, recu_ms: int | None = None) -> None:
        """Écrit la trame **telle quelle**, avec l'horodatage de RÉCEPTION LOCALE.

        🔴 L'horodatage vient de **notre horloge**, pas des données — sinon on refait la
        tautologie de `signal_age` (le « maintenant » dérivé des données **gelait** quand le
        flux calait).
        """
        t = int(time.time() * 1000) if recu_ms is None else int(recu_ms)
        self._f.write('{"recu_ms":%d,"brut":%s}\n' % (t, json.dumps(brut)))
        self._depuis_flush += 1
        if self._depuis_flush >= self._flush_tous_les:
            self._f.flush()
            self._depuis_flush = 0

    def fermer(self) -> None:
        try:
            self._f.flush()
        finally:
            self._f.close()

    def relire(self) -> Iterator[tuple[int, str]]:
        """Rejoue le spool : (recu_ms, trame brute). **Une ligne illisible est SAUTÉE, pas devinée.**"""
        if not self.chemin.exists():
            return
        for ligne in self.chemin.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ligne)
                yield int(d["recu_ms"]), str(d["brut"])
            except Exception:  # noqa: BLE001
                continue

    def __enter__(self) -> "RawSpool":
        return self

    def __exit__(self, *_e: object) -> None:
        self.fermer()


@dataclass(slots=True)
class FileBornee:
    """#502 — La file qui **protège la socket**. Bornée, et qui COMPTE ce qu'elle jette.

    ***Un consommateur lent ne doit jamais bloquer la socket.***
    Quand la file est pleine : on jette le **PLUS ANCIEN**. Le marché ne s'intéresse pas à un
    carnet vieux de trois minutes.
    """
    taille_max: int = TAILLE_FILE_PAR_DEFAUT
    age_max_ms: int = AGE_MAX_MS
    compteurs: Compteurs = field(default_factory=Compteurs)
    _q: deque = field(default_factory=deque)

    def __post_init__(self) -> None:
        if self.taille_max < 1:
            raise ValueError("une file de taille < 1 ne protege rien")
        self._q = deque(maxlen=None)     # on gere l'eviction NOUS-MEMES pour la COMPTER

    def deposer(self, message: Any, *, recu_ms: int) -> bool:
        """Dépose sans **jamais** bloquer. Rend `False` si un message a dû être jeté."""
        self.compteurs.recus += 1
        jete = False
        while len(self._q) >= self.taille_max:
            self._q.popleft()                       # le PLUS ANCIEN
            self.compteurs.jetes_file_pleine += 1
            jete = True
        self._q.append((int(recu_ms), message))
        return not jete

    def retirer(self, *, maintenant_ms: int) -> tuple[int, Any] | None:
        """Retire le plus ancien message **encore frais**. Les périmés sont jetés ET comptés.

        🔴 `maintenant_ms` vient de l'appelant (**horloge locale**), jamais des données.
        """
        while self._q:
            t, m = self._q.popleft()
            if int(maintenant_ms) - t > self.age_max_ms:
                self.compteurs.jetes_trop_vieux += 1
                continue                            # trop vieux : on ne le traite PAS
            self.compteurs.traites += 1
            return t, m
        return None

    def __len__(self) -> int:
        return len(self._q)

    @property
    def pleine(self) -> bool:
        return len(self._q) >= self.taille_max


def sante(compteurs: Compteurs, *, seuil_alerte: float = 0.01) -> dict[str, Any]:
    """**Le voyant qui ne peut PAS être soudé au vert.** (cf. le panneau SÉCURITÉ qui mentait.)"""
    t = compteurs.taux_de_perte
    if compteurs.recus == 0:
        return {"etat": "NON_MESURE", "detail": "aucun message recu -- **pas un feu vert**",
                "real_execution": False}
    if t > seuil_alerte:
        return {"etat": "DEGRADE",
                "detail": "**%.2f %% des messages sont jetes** (seuil %.2f %%). Le consommateur "
                          "est trop lent, ou le flux trop dense. La socket, elle, n'a PAS bloque."
                          % (t * 100, seuil_alerte * 100),
                "taux_de_perte": round(t, 6), "real_execution": False}
    return {"etat": "OK", "taux_de_perte": round(t, 6), "real_execution": False}


__all__ = [
    "AGE_MAX_MS", "MOTIF_FILE_PLEINE", "MOTIF_TROP_VIEUX", "TAILLE_FILE_PAR_DEFAUT",
    "Compteurs", "FileBornee", "RawSpool", "sante",
]
