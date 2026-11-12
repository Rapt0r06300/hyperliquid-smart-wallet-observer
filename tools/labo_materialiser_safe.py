#!/usr/bin/env python3
"""Étape 1 du labo (vérification SAFE + matérialisation de l'espace de travail) dans un processus à part.

POURQUOI. Cette étape charge tout le corpus : 16 Go de pic sur le corpus réel du 2026-11-12. Faite
dans le processus du labo, cette mémoire n'est jamais rendue au système (le tas reste fragmenté) et
toute la suite — reconstruction des cycles, recherche — travaille dans un tas encombré : 16 Go occupés
pendant la recherche au lieu de 5, et une étape 3 quatre fois plus lente que dans un processus neuf.
Ici le processus se termine dès que l'espace de travail est écrit : toute sa mémoire est rendue.

[M1 — GOUVERNEUR BRANCHÉ, 2026-11-12] C'est CE processus que le système a tué deux fois le 12/11
(16 Go demandés, 6 Go libres). Il consulte donc maintenant le gouverneur de mémoire
(``hl_observer.ops.budget_ram``) à trois moments, et n'abandonne jamais de lui-même :

* AVANT de charger : état mémoire journalisé ; si la pression est ROUGE, on souffle (attente BORNÉE)
  puis on continue quand même, en l'annonçant — bloquer indéfiniment serait pire ;
* PENDANT le chargement : contrôle de pression À INTERVALLE (jamais à chaque message : lire la RAM
  coûte, et cette étape émet des milliers de lignes), avec une courte respiration si ROUGE ;
* APRÈS : état mémoire final journalisé (observabilité M5).

Et si l'OS refuse malgré tout la mémoire, ``MemoryError`` est rattrapé et converti en message
EXPLOITABLE + code de sortie 3, au lieu d'une trace de pile illisible : l'appelant sait alors qu'il
doit réduire l'ampleur, pas chercher un bug.

PROTOCOLE. Appelé par ``tools/alina_quant_lab_console.py`` :

    python tools/labo_materialiser_safe.py <recovery> <workspace> <fichier_resultat>

* progression : une ligne par message sur la sortie standard, préfixée de ``PROGRES<tab>`` ;
* résultat : le dictionnaire rendu par ``materialize_safe_workspace``, sérialisé tel quel (mêmes types)
  dans ``<fichier_resultat>``, écrit puis renommé (jamais de fichier à moitié écrit).

PAPER / lecture seule : aucune requête réseau, aucun ordre.
"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

PREFIXE_PROGRES = "PROGRES\t"

# Lire la RAM a un coût et cette étape émet des milliers de messages : on ne contrôle la pression
# qu'une fois toutes les N secondes. Assez souvent pour réagir, assez rare pour ne rien ralentir.
INTERVALLE_CONTROLE_S = 20.0

# Respiration accordée quand la pression est ROUGE. Volontairement COURTE : on cherche à laisser le
# système reprendre son souffle, pas à mettre le pipeline en pause longue.
RESPIRATION_MAX_S = 20.0

CODE_SORTIE_MEMOIRE = 3

# Sentinelle : `gouverneur` non fourni => on cherche le gouverneur officiel ;
# `gouverneur=None` => surveillance EXPLICITEMENT desactivee (sans cette distinction,
# impossible de tourner sciemment sans surveillance, ni de le tester).
_AUTO = object()


def _gouverneur():
    """Le gouverneur, ou ``None`` s'il est introuvable. Son absence ne doit jamais bloquer l'étape."""
    try:
        from hl_observer.ops import budget_ram
    except Exception:  # noqa: BLE001 — l'étape doit tourner même sans le gouverneur
        return None
    return budget_ram


def surveillant_memoire(annoncer, *, gouverneur=_AUTO, horloge=None, dormir=None,
                        intervalle_s: float = INTERVALLE_CONTROLE_S,
                        respiration_s: float = RESPIRATION_MAX_S):
    """Fabrique le contrôle de pression À INTERVALLE à appeler pendant une boucle longue.

    Renvoie une fonction ``verifier()`` qui, au plus une fois par ``intervalle_s`` :
    journalise l'état mémoire et, si la pression est ROUGE, souffle brièvement (attente bornée).
    Ne lève jamais. Tout est injectable pour les tests (gouverneur, horloge, sommeil).
    ``gouverneur`` non fourni : on prend le gouverneur officiel. ``gouverneur=None`` :
    surveillance désactivée (``verifier()`` renvoie alors toujours ``None``).
    """
    gouv = _gouverneur() if gouverneur is _AUTO else gouverneur
    horloge = horloge or time.monotonic
    dernier = [float(horloge())]

    def verifier(*, forcer: bool = False) -> dict | None:
        if gouv is None:
            return None
        maintenant = float(horloge())
        if not forcer and (maintenant - dernier[0]) < max(0.0, float(intervalle_s)):
            return None
        dernier[0] = maintenant
        try:
            d = gouv.decision()
            annoncer(gouv.journal_memoire("etape1"))
            if d["action"] == gouv.PAUSER:
                annoncer(f"memoire ROUGE — {d['raison']}")
                r = gouv.attendre_que_ca_respire(limite_s=respiration_s, dormir=dormir,
                                                 horloge=horloge)
                annoncer("memoire : " + ("ca respire, on continue" if r["a_respire"]
                                         else "toujours tendue, on continue en mode degrade"))
            return d
        except Exception as exc:  # noqa: BLE001 — la surveillance ne doit JAMAIS casser l'étape
            annoncer(f"surveillance memoire indisponible ({type(exc).__name__}) — on continue")
            return None

    return verifier


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        print("usage : labo_materialiser_safe.py <recovery> <workspace> <fichier_resultat>", file=sys.stderr)
        return 2
    recovery, workspace, sortie = (Path(argument) for argument in arguments)
    from hl_observer.backtesting.copy_vault_local_lab import materialize_safe_workspace

    def progres(message: object) -> None:
        print(PREFIXE_PROGRES + str(message).replace("\r", " ").replace("\n", " "), flush=True)

    verifier = surveillant_memoire(progres)
    verifier(forcer=True)                       # état AVANT de charger (et respiration si ROUGE)

    def progres_surveille(message: object) -> None:
        progres(message)
        verifier()                              # contrôle à intervalle, pendant le chargement

    try:
        resultat = materialize_safe_workspace(recovery, workspace, progress=progres_surveille)
    except MemoryError:
        gouv = _gouverneur()
        etat = gouv.journal_memoire("etape1") if gouv is not None else "(gouverneur indisponible)"
        print(f"MEMOIRE INSUFFISANTE pour l'etape 1. {etat}. "
              f"Reduisez l'ampleur (moins de jours/coins) ou liberez de la RAM, puis relancez : "
              f"ce n'est pas un bug du code.", file=sys.stderr, flush=True)
        return CODE_SORTIE_MEMOIRE

    verifier(forcer=True)                       # état APRÈS (observabilité M5)
    temporaire = sortie.with_name(sortie.name + ".tmp")
    temporaire.write_bytes(pickle.dumps(resultat, protocol=pickle.HIGHEST_PROTOCOL))
    temporaire.replace(sortie)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
