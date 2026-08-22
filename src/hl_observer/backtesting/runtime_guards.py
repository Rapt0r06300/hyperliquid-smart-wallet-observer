"""Résilience runtime — cœurs PURS, testés (le câblage dans le poller reste à faire côté serveur).
Exécution du backlog : parent_alive (IMPROVE-01, watchdog anti-orphelin), heartbeat_stale
(IMPROVE-02, détection de gel), rotate_logs (IMPROVE-03), source_health (IMPROVE-04),
EventBus (IDEA-33, architecture event-driven). Aucun ordre.
"""
from __future__ import annotations

import glob
import os
import shutil
import time
from hl_observer.ops.echec_silencieux import noter as _noter_echec

# ============================================================================================
# 🔴🔴 LE CTRL-C QUE PERSONNE N'A TAPE : `os.kill(pid, 0)` (trouve le 2026-07-13, #600)
# ============================================================================================
#
# Pendant DEUX JOURS, un `KeyboardInterrupt` fantome a tue des mesures, des audits, et la suite
# de tests complete. J'ai accuse -- et corrige -- trois sous-processus qui relancaient pytest
# sans isoler leur groupe (`audit_report`, `couverture_de_lignes`, `test_env_hermetique`).
# **Aucun des trois n'etait le coupable.** Le vrai coupable est cette fonction, et il tient en
# une ligne :
#
#     os.kill(pid, 0)      # « signal 0 = simple test d'existence »   <- VRAI sur Unix. FAUX ici.
#
# Sur Windows, `signal.CTRL_C_EVENT` **VAUT 0**. Et `os.kill()` de CPython, sur Windows, fait :
#
#     if sig in (CTRL_C_EVENT, CTRL_BREAK_EVENT):
#         GenerateConsoleCtrlEvent(sig, pid)      # <- un VRAI Ctrl-C, au GROUPE de la console
#     else:
#         TerminateProcess(...)
#
# Donc l'idiome Unix le plus banal du monde -- « ce PID existe-t-il ? » -- **tire un Ctrl-C sur
# toute la console** quand il tourne sous Windows. `test_runtime_guards.py` appelait
# `parent_alive(os.getpid())` : la suite se Ctrl-C elle-meme, au milieu de son propre run.
#
# Et l'ironie est totale : cette fonction est le **watchdog anti-orphelin** (IMPROVE-01). Sa
# raison d'etre est de PROTEGER la session. Sous Windows, elle la TUAIT. Si elle avait ete
# branchee dans le poller, chaque battement du watchdog aurait ferme la simulation qu'il garde.
#
# LECON : *une fonction qui s'appelle « simple test d'existence » n'est pas forcement inoffensive.
# Le commentaire disait la verite sur Unix ; le code s'executait sur Windows.*
# ============================================================================================

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5


def _existe_sous_windows(pid: int) -> bool:
    """Teste l'existence d'un PID sans JAMAIS envoyer de signal. Par l'API Win32, directement."""
    if type(pid) is not int or pid <= 0:
        return False

    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ACCES REFUSE = le process EXISTE (il appartient a quelqu'un d'autre). Le confondre avec
        # « mort » ferait s'auto-terminer un enfant dont le parent tourne sous un autre compte.
        return k32.GetLastError() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True                      # on ne SAIT pas -> on ne tue pas l'enfant
        return code.value == _STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def _existe_sous_posix(pid: int) -> bool:
    """POSIX SEULEMENT. Le signal 0 y est un vrai no-op : le noyau verifie les droits, puis rend.

    La garde ci-dessous n'est pas decorative. Elle rend l'appel **physiquement inexecutable** sous
    Windows -- et c'est aussi ce que l'invariant `test_aucun_ctrl_c_deguise_en_test_d_existence`
    exige pour tolerer un `os.kill(pid, 0)` dans du code de production : un `os.kill(x, 0)` nu,
    lui, fait rougir la suite. *Isoler l'idiome dangereux derriere un refus explicite, plutot que
    d'affaiblir le detecteur qui l'a trouve.*
    """
    if os.name == "nt":
        raise RuntimeError(
            "os.kill(pid, 0) est INTERDIT sous Windows : signal 0 == CTRL_C_EVENT "
            "-> GenerateConsoleCtrlEvent -> un vrai Ctrl-C a toute la console (cf. #600)."
        )
    try:
        os.kill(pid, 0)          # POSIX : la, et SEULEMENT la, le signal 0 est bien un no-op
        return True
    except PermissionError:
        return True              # existe, mais pas les droits -> vivant
    except OSError:
        return False


def parent_alive(pid) -> bool:
    """True si le process parent existe encore. Si False -> l'enfant doit se terminer seul
    (fix bulletproof des orphelins quand on ferme la fenêtre par la croix).

    ⚠️ NE JAMAIS revenir a `os.kill(pid, 0)` : sur Windows, 0 == CTRL_C_EVENT (voir l'entete).
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError, OverflowError):
        return False
    # ROBUSTESSE (fuzzing 2026-07-11) : un PID absurde faisait lever OverflowError a os.kill
    # ("signed integer is greater than maximum") -> le watchdog CRASHAIT au lieu de proteger.
    if pid <= 0 or pid > 2**31 - 1:
        return False

    if os.name == "nt":
        try:
            return _existe_sous_windows(pid)
        except OSError:
            return False

    return _existe_sous_posix(pid)


def heartbeat_stale(last_ts: float, now: float, *, threshold: float) -> bool:
    """True si le heartbeat est trop vieux -> la boucle est gelée -> relance propre."""
    return (float(now) - float(last_ts)) > float(threshold)


def rotate_logs(directory: str, *, max_bytes: int = 10_000_000, keep: int = 5) -> list:
    """Archive (sans supprimer) les logs trop gros, et purge au-delà de `keep` archives."""
    archived = []
    arch = os.path.join(directory, "_archive")
    for p in glob.glob(os.path.join(directory, "*.log")):
        try:
            if os.path.getsize(p) > max_bytes:
                os.makedirs(arch, exist_ok=True)
                dest = os.path.join(arch, f"{os.path.basename(p)}.{int(time.time() * 1000)}")
                shutil.move(p, dest)
                open(p, "w").close()          # on recrée un fichier vide
                archived.append(dest)
        except OSError:
            _noter_echec("hl_observer/backtesting/runtime_guards.py:135")
    files = sorted(glob.glob(os.path.join(arch, "*")), key=os.path.getmtime)
    if len(files) > keep:
        for old in files[:-keep]:
            try:
                os.remove(old)
            except OSError:
                _noter_echec("hl_observer/backtesting/runtime_guards.py:142")
    return archived


def source_health(last_seen: dict, now: float, *, max_age: float) -> dict:
    """État de chaque source de données : OK ou STALE (donnée trop vieille = on ne trade pas)."""
    return {
        name: ("OK" if (float(now) - float(ts)) <= float(max_age) else "STALE")
        for name, ts in last_seen.items()
    }


class EventBus:
    """Bus d'événements (architecture event-driven) : découple producteurs et consommateurs."""

    def __init__(self):
        self._subs = {}

    def subscribe(self, topic: str, handler) -> None:
        self._subs.setdefault(topic, []).append(handler)

    def publish(self, topic: str, event) -> int:
        handlers = self._subs.get(topic, [])
        for h in handlers:
            h(event)
        return len(handlers)
