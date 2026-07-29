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
import resource_policy as RES

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

    def _processus_du_script(self, nom: str) -> list[dict]:
        """Repère les collecteurs déjà lancés, même s'ils viennent d'un ancien run.

        L'ancien anti-doublon ne connaissait que le PID de ``superviseur.json``.
        Après un crash du lanceur, un collecteur pouvait donc survivre puis être
        lancé une seconde fois, doublant CPU, réseau et écritures. On adopte un
        processus existant; on signale les doublons sans les tuer automatiquement.
        """
        try:
            import psutil  # type: ignore
        except Exception:  # noqa: BLE001
            return []
        argv = self.collecteurs.get(nom) or []
        if not argv:
            return []
        script = Path(argv[0])
        cible = (script if script.is_absolute() else self.root / script).resolve()
        trouves = []
        for p in psutil.process_iter(["pid", "cmdline", "create_time", "cwd"]):
            try:
                if int(p.info["pid"]) == os.getpid():
                    continue
                cmdline = p.info.get("cmdline") or []
                cwd = Path(p.info.get("cwd") or self.root)
                correspond = False
                for arg in cmdline[1:]:
                    if not str(arg).lower().endswith(".py"):
                        continue
                    ap = Path(arg)
                    resolu = (ap if ap.is_absolute() else cwd / ap).resolve()
                    if resolu == cible:
                        correspond = True
                        break
                if correspond:
                    trouves.append({
                        "pid": int(p.info["pid"]),
                        "start": float(p.info.get("create_time") or 0.0) or None,
                        "script": str(cible),
                    })
            except Exception:  # noqa: BLE001
                continue
        return sorted(trouves, key=lambda x: (x.get("start") or 0.0, x["pid"]))

    # ── cycle de vie ──
    def demarrer_un(self, nom: str, *, lancer=None) -> dict:
        """Démarre un collecteur s'il n'est pas déjà vivant (anti-doublon au resume). `lancer` injectable
        pour les tests (sinon subprocess read-only, stderr capturé dans un fichier)."""
        e = self.etat.get(nom, {"restart_count": 0})
        if e.get("pid") and _proc_vivant(e["pid"], e.get("start")):
            existants = self._processus_du_script(nom)
            return {"nom": nom, "etat": "DEJA_VIVANT", "pid": e["pid"],
                    "doublons_detectes": max(0, len(existants) - 1)}
        existants = self._processus_du_script(nom)
        if existants:
            adopte = existants[0]
            self.etat[nom] = {
                "pid": adopte["pid"],
                "start": adopte["start"],
                "restart_count": e.get("restart_count", 0),
                "derniere_erreur": None,
                "adopte_processus_existant": True,
                "doublons_detectes": max(0, len(existants) - 1),
            }
            self._sauver()
            return {
                "nom": nom,
                "etat": "ADOPTE_EXISTANT",
                "pid": adopte["pid"],
                "doublons_detectes": max(0, len(existants) - 1),
            }
        try:
            if lancer is not None:
                pid = int(lancer(nom, self.collecteurs[nom]))
            else:
                self.rundir.mkdir(parents=True, exist_ok=True)
                err = (self.rundir / ("stderr_%s.log" % nom)).open("a", encoding="utf-8")   # stderr -> fichier
                # Windows : groupe de processus dédié (permet un CTRL_BREAK_EVENT coopératif à l'arrêt)
                flags = 0
                if os.name == "nt":
                    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                flags = RES.subprocess_creation_flags(flags)
                p = subprocess.Popen([sys.executable, *self.collecteurs[nom]], cwd=str(RACINE),
                                     stdout=subprocess.DEVNULL, stderr=err, creationflags=flags)
                self.procs[nom] = p
                pid = p.pid
            self.etat[nom] = {"pid": pid, "start": (_create_time(pid) if pid else None),
                              "restart_count": e.get("restart_count", 0), "derniere_erreur": None}
            self._dernier_restart[nom] = time.time()
        except Exception as ex:  # noqa: BLE001
            self.etat[nom] = {**e, "pid": None, "derniere_erreur": str(ex)[:160]}
        self._sauver()
        return {"nom": nom, "etat": "DEMARRE", "pid": self.etat[nom].get("pid")}

    def demarrer_tous(self, *, lancer=None, etaler: bool = True, dormir=None) -> dict:
        """IDEA-7 (staggered startup) : les collecteurs ne démarrent plus TOUS dans la même milliseconde.
        Un plan de démarrage déterministe (décalage + jitter stable par nom) évite le burst synchronisé et
        le thundering herd sur les limites Hyperliquid (10 connexions/IP, 30 nouvelles connexions/min).
        `dormir` est injectable pour les tests (aucune attente réelle)."""
        noms = list(self.collecteurs)
        if not etaler:
            return {n: self.demarrer_un(n, lancer=lancer) for n in noms}
        try:
            import demarrage_etale as DEM
            plan = DEM.plan_demarrage(noms)
        except Exception:  # noqa: BLE001 — sans le module, on démarre comme avant (jamais de blocage)
            plan = [(n, 0.0) for n in noms]
        attendre = dormir if dormir is not None else time.sleep
        out, precedent = {}, 0.0
        for nom, delai_ms in plan:
            pause = max(0.0, float(delai_ms) - precedent) / 1000.0
            if pause > 0:
                attendre(pause)
            precedent = float(delai_ms)
            out[nom] = {**self.demarrer_un(nom, lancer=lancer), "delai_demarrage_ms": delai_ms}
        return out

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

    def _arret_process(self, nom: str, p, *, attente_s: float = 5.0) -> str:
        """Arrêt gradué et JOURNALISÉ (P8) : 1) coopératif (SIGINT/CTRL_BREAK) ; 2) attente bornée ;
        3) terminate ; 4) TerminateProcess/kill en DERNIER recours. Rend la méthode qui a fonctionné."""
        import time as _t
        methode = "aucune"
        try:
            if os.name == "nt":
                sig = getattr(__import__("signal"), "CTRL_BREAK_EVENT", None)
                if sig is not None:
                    p.send_signal(sig); methode = "CTRL_BREAK_EVENT"       # coopératif Windows (groupe de process)
            else:
                p.send_signal(__import__("signal").SIGINT); methode = "SIGINT"
        except Exception:  # noqa: BLE001
            methode = "aucune"
        t0 = _t.time()
        while _t.time() - t0 < attente_s:                    # attente BORNÉE
            if p.poll() is not None:
                return methode + "+sortie_propre"
            _t.sleep(0.1)
        try:
            p.terminate(); methode += "+terminate"
            t0 = _t.time()
            while _t.time() - t0 < 2.0:
                if p.poll() is not None:
                    return methode
                _t.sleep(0.1)
        except Exception:  # noqa: BLE001
            pass
        try:
            p.kill(); methode += "+kill_dernier_recours"     # TerminateProcess/SIGKILL en dernier
        except Exception:  # noqa: BLE001
            pass
        return methode

    def arreter_tous(self) -> dict:
        """Arrête EXPLICITEMENT tous les enfants (coopératif -> CTRL_BREAK -> terminate -> kill), méthode
        JOURNALISÉE par collecteur. Ne tue jamais son propre PID."""
        arretes, methodes = [], {}
        for nom, p in list(self.procs.items()):
            try:
                methodes[nom] = self._arret_process(nom, p)
                arretes.append(nom)
            except Exception:  # noqa: BLE001
                methodes[nom] = "echec"
        for nom, e in self.etat.items():
            pid = e.get("pid")
            if (pid and nom not in self.procs and int(pid) != os.getpid()
                    and e.get("start") is not None and _proc_vivant(pid, e.get("start"))):
                try:
                    os.kill(int(pid), 15); arretes.append(nom); methodes[nom] = "SIGTERM_pid_oriphelin"
                except (OSError, ProcessLookupError, ValueError):
                    pass
            self.etat[nom] = {**e, "pid": None, "methode_arret": methodes.get(nom)}
        self._sauver()
        (self.rundir / "arret_methodes.json").write_text(json.dumps(methodes, ensure_ascii=False), encoding="utf-8")
        return {"arretes": arretes, "methodes": methodes}


__all__ = ["Superviseur", "HEARTBEAT_MAX_AGE_MS", "EXCHANGE_MAX_AGE_MS", "BACKOFF_S"]
