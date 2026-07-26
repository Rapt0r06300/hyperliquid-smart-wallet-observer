"""SUPERVISEUR DES COLLECTEURS (LABO-CONTINU-FINAL FINAL-14, Flo 26/07). Remplace les `start /b` aveugles :
enregistre PID + heure de démarrage de chaque collecteur, évite les doublons au resume, vérifie heartbeat +
croissance réelle, redémarre INDIVIDUELLEMENT un collecteur mort (restart_count + dernière erreur), et arrête
EXPLICITEMENT tous les enfants à la finalisation. LECTURE-SEULE : ne lance que des collecteurs read-only.
0 ordre, 0 exchange.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _create_time(pid: int) -> float | None:
    """Heure de création du process (anti-réutilisation de PID). None si indéterminable."""
    try:
        import psutil  # type: ignore
        return float(psutil.Process(int(pid)).create_time())
    except Exception:  # noqa: BLE001
        return None


def _proc_vivant(pid: int, start: float | None) -> bool:
    try:
        import psutil  # type: ignore
        if not psutil.pid_exists(int(pid)):
            return False
        # `start` = create_time enregistré au lancement : identique -> même process (pas un PID réutilisé)
        return (start is None) or abs(psutil.Process(int(pid)).create_time() - float(start)) < 2.0
    except Exception:  # noqa: BLE001
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ProcessLookupError, ValueError):
            return False


class Superviseur:
    """Gère un ensemble de collecteurs read-only. `collecteurs` = {nom: [argv...]} (scripts précis)."""

    def __init__(self, rundir: Path, collecteurs: dict):
        self.rundir = Path(rundir)
        self.collecteurs = collecteurs
        self.etat_path = self.rundir / "superviseur.json"
        self.procs: dict = {}
        self.etat = self._charger()

    def _charger(self) -> dict:
        try:
            return json.loads(self.etat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {n: {"pid": None, "start": None, "restart_count": 0, "derniere_erreur": None} for n in self.collecteurs}

    def _sauver(self):
        self.etat_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.etat_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.etat, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.etat_path)

    def demarrer_un(self, nom: str, *, lancer=None) -> dict:
        """Démarre un collecteur s'il n'est pas déjà vivant (anti-doublon au resume). `lancer` injectable
        pour les tests (sinon subprocess read-only)."""
        e = self.etat.get(nom, {"restart_count": 0})
        if e.get("pid") and _proc_vivant(e["pid"], e.get("start")):
            return {"nom": nom, "etat": "DEJA_VIVANT", "pid": e["pid"]}
        try:
            if lancer is not None:
                pid = int(lancer(nom, self.collecteurs[nom]))
            else:
                p = subprocess.Popen([sys.executable, *self.collecteurs[nom]], cwd=str(RACINE),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.procs[nom] = p
                pid = p.pid
            self.etat[nom] = {"pid": pid, "start": (_create_time(pid) if pid else None),
                              "restart_count": e.get("restart_count", 0), "derniere_erreur": None}
        except Exception as ex:  # noqa: BLE001
            self.etat[nom] = {**e, "pid": None, "derniere_erreur": str(ex)[:160]}
        self._sauver()
        return {"nom": nom, "etat": "DEMARRE", "pid": self.etat[nom].get("pid")}

    def demarrer_tous(self, *, lancer=None) -> dict:
        return {n: self.demarrer_un(n, lancer=lancer) for n in self.collecteurs}

    def surveiller(self, *, lancer=None) -> dict:
        """Redémarre INDIVIDUELLEMENT les collecteurs morts (incrémente restart_count)."""
        redémarrés = []
        for nom, e in list(self.etat.items()):
            if not (e.get("pid") and _proc_vivant(e["pid"], e.get("start"))):
                e["restart_count"] = e.get("restart_count", 0) + 1
                self.etat[nom] = e
                self.demarrer_un(nom, lancer=lancer)
                redémarrés.append(nom)
        return {"redemarres": redémarrés, "etat": self.etat}

    def arreter_tous(self) -> dict:
        """Arrête EXPLICITEMENT tous les enfants (à la finalisation)."""
        arretes = []
        for nom, p in list(self.procs.items()):
            try:
                p.terminate()
                arretes.append(nom)
            except Exception:  # noqa: BLE001
                pass
        for nom, e in self.etat.items():
            pid = e.get("pid")
            # garde-fou : ne JAMAIS tuer son propre process (PID courant) ni un PID sans create_time vérifié
            if (pid and nom not in self.procs and int(pid) != os.getpid()
                    and e.get("start") is not None and _proc_vivant(pid, e.get("start"))):
                try:
                    os.kill(int(pid), 15)
                    arretes.append(nom)
                except (OSError, ProcessLookupError, ValueError):
                    pass
            self.etat[nom] = {**e, "pid": None}
        self._sauver()
        return {"arretes": arretes}


__all__ = ["Superviseur"]
