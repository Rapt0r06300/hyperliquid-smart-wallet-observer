"""ANTI-ORPHELIN (21/07, Flo : « Q — et même la croix — doivent correctement terminer la
session »). Chaque boucle de collecteur appelle ce garde AVANT chaque passe :

  1. NOUVELLE SESSION LANCEUR : le lanceur écrit un marqueur unique à chaque démarrage ;
     une boucle démarrée sous un ANCIEN marqueur est périmée -> elle s'arrête (sinon les
     boucles se DOUBLENT à chaque relance : deux carry-feeders qui tapent l'API).
  2. MOTEUR SILENCIEUX : les collecteurs n'existent que pour nourrir le moteur. Si le
     moteur n'a plus donné signe de vie depuis 20 min (ni décision, ni état UI), la boucle
     s'arrête proprement — c'est le filet pour la CROIX, les crashs, les kills brutaux.
     Grâce de démarrage : marqueur récent = le moteur chauffe encore, on patiente.

Sortie 0 = vivre, 1 = s'arrêter (motif imprimé, journalisé par la boucle). Lecture seule.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

#: silence moteur toléré avant l'arrêt propre (le superviseur constate en <20 min aussi)
GRACE_S = 20 * 60.0

MARQUEUR_RELPATH = Path("runtime") / "data" / "lanceur_session_marqueur.txt"
HEARTBEATS = (Path("runtime") / "data" / "carry_hype_paper_decisions.jsonl",
              Path("runtime") / "data" / "ui_simulation_state.json")


def doit_vivre(marqueur_au_demarrage: str, root: str | Path = ".",
               *, now: float | None = None) -> tuple[bool, str]:
    racine = Path(root)
    t = now if now is not None else time.time()
    chemin_marqueur = racine / MARQUEUR_RELPATH
    try:
        courant = chemin_marqueur.read_text(encoding="utf-8").strip()
    except OSError:
        courant = ""
    m0 = (marqueur_au_demarrage or "").strip()
    if m0 and courant and courant != m0:
        return False, "NOUVELLE_SESSION_LANCEUR : cette boucle appartient a une session finie"
    for hb in HEARTBEATS:
        try:
            if t - (racine / hb).stat().st_mtime < GRACE_S:
                return True, ""
        except OSError:
            continue
    try:
        if t - chemin_marqueur.stat().st_mtime < GRACE_S:
            return True, ""      # session toute neuve : le moteur chauffe encore
    except OSError:
        pass
    return False, ("MOTEUR_SILENCIEUX_20MIN : anti-orphelin — le collecteur suit la vie du "
                   "moteur (Q, croix, crash : tout finit proprement)")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    marqueur = args[0] if args else ""
    vivre, motif = doit_vivre(marqueur)
    if not vivre:
        print("  [anti-orphelin] %s" % motif)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
