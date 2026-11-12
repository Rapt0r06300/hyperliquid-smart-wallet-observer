#!/usr/bin/env python3
"""Affiche ET journalise : plus jamais une fenetre noire pendant une etape longue.

POURQUOI. Le lanceur de collecte redirigeait le scellement du coffre vers un fichier
(`>> runtime/logs/coffre_session.log`). Resultat : pendant plusieurs minutes — 113 fichiers a
certifier, dont des rubans de 77 Mo — la fenetre restait COMPLETEMENT NOIRE. Impossible de
distinguer « ca travaille » de « c'est plante », au moment precis ou on vient de lancer une
campagne de six jours. Une interface muette pendant une etape longue est un defaut, pas un detail.

Ce relais lit l'entree standard ligne par ligne, l'ECRIT A L'ECRAN (vidage immediat, donc visible
en direct) et l'AJOUTE au journal. On garde le fichier pour le diagnostic, on rend l'attente lisible.

Deux usages :

* en TUYAU   :  programme 2>&1 | python tee_console.py journal.log
* en LANCEUR :  python tee_console.py journal.log -- programme arg1 arg2

**Preferer la seconde forme quand le code de sortie compte.** Derriere un tuyau, `%ERRORLEVEL%` de
Windows renvoie le code du DERNIER maillon (ce relais, toujours 0) : le lanceur consignerait
« certification reussie » meme apres un echec. En mode LANCEUR, le relais execute lui-meme le
programme et ressort AVEC SON CODE A LUI — la visibilite ne coute pas le signal d'echec.

Choix deliberes :
* `errors="replace"` des deux cotes : une console en cp1252 ne doit JAMAIS faire echouer une
  certification a cause d'un caractere accentue ou d'une fleche ;
* vidage a chaque ligne : sans cela, le tampon de bloc redonnerait une fenetre noire ;
* le journal est ouvert en AJOUT, jamais en ecrasement : on ne perd pas l'historique de la session ;
* si l'ecriture du journal echoue (disque plein, fichier verrouille), on CONTINUE d'afficher :
  perdre la trace est ennuyeux, perdre la visibilite au milieu d'une campagne l'est davantage.
"""
from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path


def relayer(entree, sortie, journal) -> int:
    lignes = 0
    for ligne in entree:
        lignes += 1
        with contextlib.suppress(OSError, ValueError, UnicodeError):
            sortie.write(ligne)
            sortie.flush()
        if journal is not None:
            with contextlib.suppress(OSError, ValueError, UnicodeError):
                journal.write(ligne)
                journal.flush()
    return lignes


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    commande: list[str] = []
    if "--" in args:                      # tout ce qui suit « -- » est le programme a executer
        coupe = args.index("--")
        args, commande = args[:coupe], args[coupe + 1:]
    for flux in (sys.stdout, sys.stderr, sys.stdin):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    journal = None
    if args:
        chemin = Path(args[0])
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            journal = chemin.open("a", encoding="utf-8", errors="replace")
        except OSError as exc:            # journal impossible : on affiche quand meme
            print(f"[tee] journal indisponible ({type(exc).__name__}) — affichage seul",
                  file=sys.stderr, flush=True)
            journal = None
    try:
        if commande:
            # Mode LANCEUR : on execute, on relaie en direct, on ressort avec SON code.
            # stderr fondu dans stdout : un message d'erreur doit se voir A SA PLACE dans le flux.
            with subprocess.Popen(commande, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  bufsize=1) as proc:
                relayer(proc.stdout, sys.stdout, journal)
                return int(proc.wait())
        relayer(sys.stdin, sys.stdout, journal)
    finally:
        if journal is not None:
            with contextlib.suppress(OSError):
                journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
