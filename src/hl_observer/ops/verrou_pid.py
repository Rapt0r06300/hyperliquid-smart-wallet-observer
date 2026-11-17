"""Verrou de PID partagé : un seul écrivain à la fois sur un état de fichiers.

POURQUOI CE MODULE EXISTE (16/11/2026). Le verrou avait été écrit dans
``tools/rattrapage_complet.py`` pour empêcher deux rattrapages simultanés. Puis on a voulu que le
rattrapage **scelle lui-même** ses résultats dans le coffre à la fin de son passage — et le
scelleur ``tools/sceller_coffre_local.py`` n'avait AUCUN verrou, alors que la campagne le relance
déjà toutes les 30 minutes (``coffre-certificateur``). Deux scellages en parallèle écrivent le même
``SOURCES_TRAITEES.json`` : le dernier à écrire efface les décalages d'octets de l'autre. Les
données ne sont pas perdues, mais le registre de ce qui est scellé l'est — et c'est lui qui dit au
labo ce qu'il peut lire. D'où un verrou, et un seul, partagé par les deux outils.

Rien d'« atomique » n'est promis ici : deux processus qui démarrent dans la même milliseconde
peuvent tous deux obtenir le verrou. Il protège du cas RÉEL (un passage lancé à la main pendant
qu'un autre tourne depuis 20 minutes), pas d'une course de nanosecondes.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from pathlib import Path

from hl_observer.backtesting.runtime_guards import _existe_sous_posix
from hl_observer.ops.echec_silencieux import noter as _noter_echec

#: Au-delà, un verrou est considéré comme le reste d'un passage tué (le PC coupe les runs longs).
PERIME_S_DEFAUT = 6 * 3600.0


def pid_vivant(pid: int) -> bool:
    """Ce PID tourne-t-il ? **Jamais `os.kill` sur Windows** : il TUERAIT le processus.

    `os.kill(pid, 0)` est l'idiome POSIX pour « sonder sans toucher ». Sous Windows, Python
    n'implémente pas le signal 0 : tout signal autre que CTRL_C_EVENT/CTRL_BREAK_EVENT appelle
    `TerminateProcess`. Le test aurait donc tué le processus qu'il cherchait à détecter.

    `tasklist` sert de repli — en OCTETS. Sur un Windows français il répond en cp850, et le
    décoder en UTF-8 levait une `UnicodeDecodeError` dans le fil de lecture de `subprocess` : le
    verrou devenait indécidable (défaut vu en test le 15/11).

    En cas de doute, on répond VIVANT : voler un verrou à tort fait tourner deux écrivains.
    """
    if pid <= 0:
        return False
    try:
        import psutil                                    # présent sur la machine de collecte
        return bool(psutil.pid_exists(int(pid)))
    except Exception as exc:                             # noqa: BLE001 — psutil est optionnel
        # Compté, jamais muet : si psutil disparaît, le repli `tasklist` prend le relais et un
        # compteur qui monte dit pourquoi le verrou est devenu plus lent à décider.
        _noter_echec("ops/verrou_pid.py:psutil_indisponible", exc)
    if os.name == "nt":
        try:
            sortie = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                    capture_output=True, timeout=20)      # OCTETS, pas de texte
        except (OSError, subprocess.SubprocessError):
            return True                     # dans le doute, on NE vole PAS le verrou
        brut = (sortie.stdout or b"").decode("utf-8", errors="replace")
        return str(pid) in brut
    # POSIX : l'idiome « signal 0 » vit derrière la garde de `runtime_guards`, qui le rend
    # physiquement inexécutable sous Windows (où signal 0 == CTRL_C_EVENT, un vrai Ctrl-C envoyé à
    # toute la console). Un `os.kill(pid, 0)` nu ici faisait rougir l'invariant du dépôt.
    try:
        return bool(_existe_sous_posix(int(pid)))
    except (OSError, RuntimeError):
        return True                         # dans le doute, on NE vole PAS le verrou


def prendre(chemin: Path, *, perime_s: float = PERIME_S_DEFAUT,
            quoi: str = "un passage") -> tuple[bool, str]:
    """``(obtenu, explication)``. Un verrou vivant interdit un second écrivain."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        pid, depuis = int(brut.get("pid") or 0), float(brut.get("ts") or 0.0)
    except (OSError, ValueError, TypeError, AttributeError):
        pid, depuis = 0, 0.0
    # Un horodatage ABSENT ou illisible (0.0) n'est pas « très vieux » : c'est INCONNU. Dans ce
    # cas seul le PID décide, et un PID vivant fait refuser — voler un verrou à tort ferait tourner
    # deux écrivains, ce qui est précisément le problème qu'il empêche.
    age = time.time() - depuis if depuis > 0.0 else None
    if pid and pid_vivant(pid) and (age is None or age < float(perime_s)):
        return False, (f"{quoi} tourne deja (PID {pid}"
                       + (f", depuis {age / 60:.0f} min" if age is not None else "") + ")")
    explication = ""
    if pid:
        explication = (f"verrou PERIME recupere (PID {pid} absent ou plus vieux que "
                       f"{float(perime_s) / 3600:.0f} h) — reste probable d'un passage tue")
    chemin.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")
    return True, explication


def rendre(chemin: Path) -> None:
    with contextlib.suppress(OSError):
        Path(chemin).unlink(missing_ok=True)
