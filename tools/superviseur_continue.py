"""SUPERVISEUR DES COLLECTEURS (Flo 26/07, FINAL-14 + PT-9 santé/backoff). Remplace les `start /b` aveugles :
enregistre PID + create_time de chaque collecteur, évite les doublons au resume, VÉRIFIE la santé (heartbeat
frais, croissance des écritures, âge du dernier exchange_ts), détecte un collecteur VIVANT-mais-FIGÉ, redémarre
INDIVIDUELLEMENT (restart_count + dernière erreur), avec BACKOFF anti-tempête de reconnexions, capture le
stderr dans un fichier, et arrête EXPLICITEMENT tous les enfants à la finalisation (arrêt coopératif d'abord,
jamais son propre PID). LECTURE-SEULE : ne lance que des collecteurs read-only. 0 ordre, 0 exchange.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
HEARTBEAT_MAX_AGE_MS = 120_000            # au-delà -> collecteur figé (heartbeat trop vieux)
EXCHANGE_MAX_AGE_MS = 300_000             # au-delà -> flux figé (dernier exchange_ts trop vieux)
BACKOFF_S = 20.0                          # anti-tempête : pas plus d'un restart par collecteur / BACKOFF_S


def _create_time(pid: int) -> float | None:
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
        return (start is None) or abs(psutil.Process(int(pid)).create_time() - float(start)) < 2.0
    except Exception:  # noqa: BLE001
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ProcessLookupError, ValueError):
            return False


class Superviseur:
    """Gère un ensemble de collecteurs read-only. `collecteurs` = {nom: [argv...]}."""

    def __init__(self, rundir: Path, collecteurs: dict, *, root: Path | None = None,
                 heartbeat_max_age_ms: int = HEARTBEAT_MAX_AGE_MS, backoff_s: float = BACKOFF_S):
        self.rundir = Path(rundir)
        self.collecteurs = collecteurs
        self.root = Path(root) if root else RACINE
        self.hb_max_age = int(heartbeat_max_age_ms)
        self.backoff_s = float(backoff_s)
        self.etat_path = self.rundir / "superviseur.json"
        self.procs: dict = {}
        self._dernier_restart: dict = {}
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

    # ── santé (PT-9) ──
    def sante(self, nom: str, *, maintenant_ms=None) -> dict:
        """Vivant ? figé ? Combine liveness process + fraîcheur du heartbeat + âge du dernier exchange_ts."""
        e = self.etat.get(nom, {})
        vivant = bool(e.get("pid") and _proc_vivant(e["pid"], e.get("start")))
        try:
            import heartbeat_collecteur as HB
            age = HB.age_ms(self.root, nom, maintenant_ms=maintenant_ms)
            hb = HB.lire(self.root, nom)
        except Exception:  # noqa: BLE001
            age, hb = None, {}
        fige = bool(vivant and age is not None and age > self.hb_max_age)
        ex_ts = hb.get("dernier_exchange_ts")
        flux_fige = False
        if vivant and ex_ts is not None:
            now = int(maintenant_ms if maintenant_ms is not None else time.time() * 1000)
            try:
                flux_fige = (now - int(ex_ts)) > EXCHANGE_MAX_AGE_MS
            except (TypeError, ValueError):
                flux_fige = False
        return {"nom": nom, "vivant": vivant, "heartbeat_age_ms": age, "fige": fige, "flux_fige": flux_fige,
                "n_passes": hb.get("n_passes"), "restart_count": e.get("restart_count", 0),
                "sain": bool(vivant and not fige and not flux_fige)}

    def _backoff_ok(self, nom: str) -> bool:
        dernier = self._dernier_restart.get(nom, 0.0)
        return (time.time() - dernier) >= self.backoff_s

    # ── cycle de vie ──
    def demarrer_un(self, nom: str, *, lancer=None) -> dict:
        """Démarre un collecteur s'il n'est pas déjà vivant (anti-doublon au resume). `lancer` injectable
        pour les tests (sinon subprocess read-only, stderr capturé dans un fichier)."""
        e = self.etat.get(nom, {"restart_count": 0})
        if e.get("pid") and _proc_vivant(e["pid"], e.get("start")):
            return {"nom": nom, "etat": "DEJA_VIVANT", "pid": e["pid"]}
        try:
            if lancer is not None:
                pid = int(lancer(nom, self.collecteurs[nom]))
            else:
                self.rundir.mkdir(parents=True, exist_ok=True)
                err = (self.rundir / ("stderr_%s.log" % nom)).open("a", encoding="utf-8")   # stderr -> fichier
                p = subprocess.Popen([sys.executable, *self.collecteurs[nom]], cwd=str(RACINE),
                                     stdout=subprocess.DEVNULL, stderr=err)
                self.procs[nom] = p
                pid = p.pid
            self.etat[nom] = {"pid": pid, "start": (_create_time(pid) if pid else None),
                              "restart_count": e.get("restart_count", 0), "derniere_erreur": None}
            self._dernier_restart[nom] = time.time()
        except Exception as ex:  # noqa: BLE001
            self.etat[nom] = {**e, "pid": None, "derniere_erreur": str(ex)[:160]}
        self._sauver()
        return {"nom": nom, "etat": "DEMARRE", "pid": self.etat[nom].get("pid")}

    def demarrer_tous(self, *, lancer=None) -> dict:
        return {n: self.demarrer_un(n, lancer=lancer) for n in self.collecteurs}

    def surveiller(self, *, lancer=None, maintenant_ms=None) -> dict:
        """Redémarre INDIVIDUELLEMENT les collecteurs MORTS ou VIVANTS-MAIS-FIGÉS (heartbeat trop vieux),
        avec BACKOFF (jamais une tempête de reconnexions). Incrémente restart_count + note la raison."""
        redémarrés = []
        for nom in list(self.collecteurs):
            s = self.sante(nom, maintenant_ms=maintenant_ms)
            besoin = (not s["vivant"]) or s["fige"] or s["flux_fige"]
            if besoin and self._backoff_ok(nom):
                e = self.etat.get(nom, {})
                raison = "MORT" if not s["vivant"] else ("FIGE" if s["fige"] else "FLUX_FIGE")
                if s["vivant"] and nom in self.procs:        # figé : on arrête d'abord proprement
                    try:
                        self.procs[nom].terminate()
                    except Exception:  # noqa: BLE001
                        pass
                    self.etat[nom] = {**e, "pid": None}
                self.etat[nom] = {**self.etat.get(nom, {}), "restart_count": e.get("restart_count", 0) + 1,
                                  "derniere_erreur": raison}
                self.demarrer_un(nom, lancer=lancer)
                redémarrés.append({"nom": nom, "raison": raison})
        return {"redemarres": redémarrés, "etat": self.etat}

    def arreter_tous(self) -> dict:
        """Arrête EXPLICITEMENT tous les enfants (terminate coopératif), jamais son propre PID."""
        arretes = []
        for nom, p in list(self.procs.items()):
            try:
                p.terminate()
                arretes.append(nom)
            except Exception:  # noqa: BLE001
                pass
        for nom, e in self.etat.items():
            pid = e.get("pid")
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


__all__ = ["Superviseur", "HEARTBEAT_MAX_AGE_MS", "EXCHANGE_MAX_AGE_MS", "BACKOFF_S"]
