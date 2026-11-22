"""Ecrit le verrou de campagne avec une IDENTITE, appele par le lanceur .cmd.

Un fichier dedie plutot qu'un `python -c` dans le .cmd : les antislashes de Windows et les
`%` de cmd se melangent tres mal avec une ligne Python entre guillemets, et un verrou qu on
n arrive pas a ecrire est pire qu un verrou aleatoire.

Ce que l ancien lanceur faisait : `echo %RANDOM%%RANDOM%> "%CV_LOCKFILE%"` -- un nombre
aleatoire, sous un commentaire annoncant << PID du cmd courant >>. Personne ne pouvait donc
savoir qui tenait le verrou, ni le valider, ni le liberer en connaissance de cause.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import collecteurs_balayage as balayage  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verrou", required=True)
    p.add_argument("--commande", default="LANCER_COLLECTEURS_COPY_VAULT.cmd")
    p.add_argument("--pid", type=int, default=None,
                   help="PID a inscrire ; par defaut le PARENT (le cmd qui nous lance)")
    args = p.parse_args(argv)
    # Le PID utile est celui du `cmd` qui detient la campagne, pas celui de ce script
    # ephemere : un verrou pointant un processus deja mort ne vaut rien.
    pid = args.pid if args.pid is not None else os.getppid()
    balayage.ecrire_verrou(args.verrou, pid=int(pid), commande=args.commande,
                           horodatage_ms=int(time.time() * 1000))
    etat = balayage.lire_verrou(args.verrou)
    print(f"[VERROU] ecrit pid={etat['pid']} motif={etat['motif']}")
    return 0 if etat["pid"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
