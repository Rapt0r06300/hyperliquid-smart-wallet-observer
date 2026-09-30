"""Lancer pytest depuis un outil SANS que son Ctrl-C ne nous tue.

LE BUG, EN UNE PHRASE
---------------------
Sur Windows, un Ctrl-C ne va pas au processus : il va a la **console entiere**. Si un outil lance
pytest comme sous-processus dans la MEME console, et que la suite declenche un Ctrl-C, le PARENT
le recoit aussi. L'outil de mesure meurt en emportant sa mesure.

Ce n'est pas theorique :
  * 2026-07-11 : `tools/audit_report.py` mourait ainsi. Corrige la-bas (CREATE_NEW_PROCESS_GROUP).
  * 2026-07-13 : `tools/couverture_de_lignes.py` est mort **exactement pareil**, deux fois de
    suite -- parce que le correctif de 2026-07-11 n'avait ete applique qu'a UN outil.

C'est la maladie du projet, encore : *une capacite presente, un chainon manquant, et personne ne
se plaint*. La reponse n'est donc PAS « recorriger a la main » : c'est un point de passage UNIQUE,
plus un invariant (`tests/test_outils_isoles_du_ctrl_c.py`) qui ROUGIT si un outil l'oublie.

⚠️ Ceci n'ouvre AUCUNE capacite nouvelle : on ne fait qu'isoler un sous-processus de test.
Aucun ordre, aucun reseau, aucune cle.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def creationflags() -> int:
    """Le drapeau qui donne au sous-processus son PROPRE groupe. 0 hors Windows (inutile)."""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def run_isole(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """`subprocess.run` + isolation du groupe de processus.

    Le Ctrl-C du sous-processus reste CHEZ LUI. Le notre continue de vivre -- et rend sa mesure.
    """
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=creationflags(),
    )
