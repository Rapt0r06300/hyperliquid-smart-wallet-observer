"""ORCHESTRATEUR du run de recherche autonome 14 h (Flo 25/07). RÉUTILISE l'archi existante — ne
reconstruit rien : RESEARCH_PARALLEL_V1 (isolation), collecter_lab_microstructure / collecter_lab_ctx
(données), execution_honnete (markouts causaux taker/maker), validation (DSR/PBO/walk-forward/placebos).

Sous-commandes : precheck · start · status · resume · stop · finalize · dry-run.

ISOLATION DURE : sortie SOUS runtime/research_lab/overnight_14h/<run_id>/ uniquement ; aucun impact
RAW/OOS/MAIN ; aucun reset ; AUCUN ordre ni paper trade (mesure pure) ; arrêt seulement par run_id signé ;
dedup labo avant start ; reprise sans doublon/perte. 0 clé, 0 signature, 0 ordre réel.

PROTOCOLE (heures depuis T0) : A découverte [0;5[ · embargo [5;6[ · B validation [6;10[ · embargo [10;11[
· C holdout scellé [11;14]. Aucun tuning après H5 ; ≤10 variantes finalistes figées ; tout trade dont
l'horizon TRAVERSE une frontière de phase est EXCLU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research_parallel import isolation as ISO  # noqa: E402

RUN_ROOT_REL = ISO.LAB_REL / "overnight_14h"
DUREE_TOTALE_S = 14 * 3600
#: frontières de phase (secondes depuis T0). Un épisode dont l'entrée OU la sortie traverse une frontière
#: est exclu (pas de fuite entre découverte, validation et holdout).
PHASES = (("A_DECOUVERTE", 0, 5 * 3600), ("EMBARGO_1", 5 * 3600, 6 * 3600),
          ("B_VALIDATION", 6 * 3600, 10 * 3600), ("EMBARGO_2", 10 * 3600, 11 * 3600),
          ("C_HOLDOUT", 11 * 3600, 14 * 3600))
MAX_FINALISTES = 10
#: 10 mécanismes HL NATIFS pré-enregistrés (distincts des variantes déjà KILL : copy, metaorder, lead-lag,
#: dislocation cross-venue, BIN_AGGRESSION_VS_HL_BBO_5S, premium-reversal, residual-momentum majors).
MECANISMES = ("OFI_TOP1", "OFI_TOP5", "OFI_TOP20", "QUEUE_MICROPRICE", "LIQUIDITY_VACUUM",
              "HL_ABSORPTION_NATIVE", "TRADE_SWEEP_BURST", "OI_VEL_ACCEL_PRICE_FUNDING",
              "FUNDING_CLOCK_DIVERGENCE", "LIQUIDATION_CASCADE_DEPTH")
#: seuils CANDIDAT (aucun assoupli après lecture). Un candidat DOIT tout passer.
CRIT = {"min_episodes": 30, "pf_min": 1.2, "dsr_min": 0.95, "pbo_max": 0.20, "cout_stress_pct": 50}

MARKOUTS_MS = (100, 250, 500, 1000, 3000, 5000, 15000, 30000, 60000,
               300000, 900000, 1800000, 3600000)


# ─────────────────────────── identité / verrou signés ───────────────────────────
def _run_root(root: Path) -> Path:
    return Path(root) / RUN_ROOT_REL


def _identite_active(root: Path) -> dict | None:
    p = _run_root(root) / "ACTIVE.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def phase_courante(elapsed_s: float) -> str:
    for nom, deb, fin in PHASES:
        if deb <= elapsed_s < fin:
            return nom
    return "FINI" if elapsed_s >= DUREE_TOTALE_S else "AVANT_T0"


def traverse_frontiere(entree_s: float, sortie_s: float) -> bool:
    """True si [entree;sortie] chevauche une frontière de phase (épisode à EXCLURE, anti-fuite)."""
    for _nom, _deb, fin in PHASES:
        if entree_s < fin <= sortie_s:
            return True
    return False


# ─────────────────────────── projection disque ───────────────────────────
def projection_disque_octets(root: Path) -> int:
    """Projette la taille 14 h depuis la vitesse d'écriture actuelle des flux micro (mesurée), plancher 2 Go."""
    d = ISO.lab_root(root) / "data"
    total = 0
    for nom in ("micro_trades", "micro_l2book", "micro_bbo", "asset_ctx", "predicted_fundings"):
        f = d / ("%s.jsonl" % nom)
        try:
            total += f.stat().st_size
        except OSError:
            pass
    # heartbeat micro donne l'âge de collecte -> extrapole (grossier, borné)
    try:
        hb = json.loads((ISO.lab_root(root) / "micro_heartbeat.json").read_text(encoding="utf-8"))
        age_s = max(60.0, (time.time() * 1000 - hb.get("ts_wall_ms", 0)) / 1000.0 + 60.0)
    except (OSError, ValueError):
        age_s = 300.0
    debit = total / age_s if age_s > 0 else 0
    return int(max(2 * 1024**3, debit * DUREE_TOTALE_S * 1.3))


# ─────────────────────────── PRECHECK (bloquant) ───────────────────────────
def _heartbeat_age_s(root: Path, rel: str):
    try:
        return time.time() - (Path(root) / rel).stat().st_mtime
    except OSError:
        return None


def _messages_micro(root: Path):
    try:
        return json.loads((ISO.lab_root(root) / "micro_heartbeat.json").read_text(encoding="utf-8")).get("messages")
    except (OSError, ValueError):
        return None


def _ws_grossit(root: Path, *, attente_s: float = 8.0) -> bool:
    """WS réellement en réception : le compteur `messages` du heartbeat micro augmente (signal robuste,
    indépendant de la latence de synchro du fichier), OU à défaut la taille du fichier trades croît."""
    f = ISO.lab_root(root) / "data" / "micro_trades.jsonl"
    m0 = _messages_micro(root)
    try:
        s0 = f.stat().st_size
    except OSError:
        s0 = -1
    time.sleep(attente_s)
    m1 = _messages_micro(root)
    try:
        s1 = f.stat().st_size
    except OSError:
        s1 = -1
    if m0 is not None and m1 is not None and m1 > m0:
        return True
    return s1 > s0 >= 0


def _reconnexions_stables(root: Path) -> bool:
    """Le collecteur micro vit (heartbeat frais) : la reconnexion se fait (on tolère des reconnexions,
    on exige seulement que le flux ne soit pas MORT)."""
    age = _heartbeat_age_s(root, str(ISO.LAB_REL / "micro_heartbeat.json"))
    return age is not None and age < 120.0


def _tests_verts(root: Path, *, rapide: bool = True) -> dict:
    """Lance le sous-ensemble de tests du LABO (vérité = doivent être verts avant le chrono)."""
    fichiers = ["tests/test_research_parallel_lot0.py", "tests/test_lab_ctx_lot1.py",
                "tests/test_execution_honnete_lot6.py", "tests/test_validation_lot7.py",
                "tests/test_lab_microstructure_lot5.py"]
    env = {**os.environ, "PYTHONPATH": str(Path(root) / "src")}
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", *fichiers],
                           cwd=str(root), env=env, capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0
        return {"verts": ok, "resume": (r.stdout.strip().splitlines() or ["?"])[-1][:120]}
    except Exception as e:  # noqa: BLE001
        return {"verts": False, "resume": "pytest KO: %s" % str(e)[:80]}


def precheck(root: Path, *, avec_tests: bool = True) -> dict:
    root = Path(root)
    disque = shutil.disk_usage(str(root))
    proj = projection_disque_octets(root)
    checks = {
        "tests_verts": _tests_verts(root) if avec_tests else {"verts": None, "resume": "sauté (dry-run léger)"},
        "instance_unique": _identite_active(root) is None,
        "heartbeat_main_frais_s": _heartbeat_age_s(root, "runtime/data/bbo_heartbeat.json"),
        "heartbeat_labo_frais_s": _heartbeat_age_s(root, str(ISO.LAB_REL / "heartbeat.json")),
        "ws_grossit": _ws_grossit(root),
        "reconnexions_stables": _reconnexions_stables(root),
        "disque_libre_go": round(disque.free / 1024**3, 1),
        "projection_14h_go": round(proj / 1024**3, 1),
        "disque_2x_ok": disque.free >= 2 * proj,
    }
    hm = checks["heartbeat_main_frais_s"]
    hl = checks["heartbeat_labo_frais_s"]
    passe = bool(
        (checks["tests_verts"]["verts"] in (True, None))
        and checks["instance_unique"]
        and hm is not None and hm < 120
        and hl is not None and hl < 180
        and checks["ws_grossit"] and checks["reconnexions_stables"] and checks["disque_2x_ok"]
    )
    return {"PRECHECK": "PASS" if passe else "FAIL", "checks": checks}


# ─────────────────────────── dedup labo ───────────────────────────
def dedup_labo(root: Path) -> dict:
    """Supprime les runs 14h ORPHELINS (ACTIVE.json sans process vivant) avant un nouveau départ. Ne
    touche jamais aux DONNÉES (archives préservées) : ne retire que le verrou orphelin."""
    ident = _identite_active(root)
    retire = None
    if ident:
        pid = ident.get("pid")
        vivant = False
        if pid:
            try:
                import signal
                os.kill(pid, 0)          # ne tue pas : teste l'existence
                vivant = True
            except (OSError, ProcessLookupError):
                vivant = False
            except Exception:  # noqa: BLE001 (Windows: os.kill(pid,0) peut lever autrement)
                vivant = True
        if not vivant:
            try:
                (_run_root(root) / "ACTIVE.json").unlink()
                retire = ident.get("run_id")
            except OSError:
                pass
    return {"verrou_orphelin_retire": retire}


# ─────────────────────────── start / identité ───────────────────────────
def demarrer(root: Path, *, dry_run: bool = False) -> dict:
    root = Path(root)
    dedup_labo(root)
    pc = precheck(root, avec_tests=not dry_run)
    if dry_run:
        return {"mode": "DRY_RUN", **pc, "note": "aucun chrono démarré ; aucun fichier de run créé"}
    if pc["PRECHECK"] != "PASS":
        return {"demarrage": "REFUSE", **pc}
    run_id = "r14h-" + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:12]
    t0 = time.time()
    rundir = _run_root(root) / run_id
    for sd in ("resultats", "ledger", "manifeste"):
        (rundir / sd).mkdir(parents=True, exist_ok=True)
    ident = {"run_id": run_id, "pid": os.getpid(), "t0_wall_ms": int(t0 * 1000),
             "t0_mono_ns": time.monotonic_ns(), "fin_prevue_wall_ms": int((t0 + DUREE_TOTALE_S) * 1000),
             "phases": [{"nom": n, "debut_s": d, "fin_s": f} for n, d, f in PHASES],
             "mecanismes": list(MECANISMES), "criteres": CRIT, "rundir": str(rundir),
             "read_only": True, "real_execution": False}
    (rundir / "run_identity.json").write_text(json.dumps(ident, ensure_ascii=False, indent=1), encoding="utf-8")
    _run_root(root).mkdir(parents=True, exist_ok=True)
    (_run_root(root) / "ACTIVE.json").write_text(json.dumps(ident, ensure_ascii=False), encoding="utf-8")
    return {"demarrage": "OK", "run_id": run_id, "t0_wall_ms": ident["t0_wall_ms"],
            "fin_prevue_wall_ms": ident["fin_prevue_wall_ms"], "rundir": str(rundir),
            "mecanismes": list(MECANISMES), **pc}


def statut(root: Path) -> dict:
    ident = _identite_active(Path(root))
    if not ident:
        return {"actif": False}
    elapsed = time.time() - ident["t0_wall_ms"] / 1000.0
    return {"actif": True, "run_id": ident["run_id"], "pid": ident.get("pid"),
            "elapsed_h": round(elapsed / 3600.0, 2), "phase": phase_courante(elapsed),
            "reste_h": round(max(0, DUREE_TOTALE_S - elapsed) / 3600.0, 2), "rundir": ident.get("rundir")}


def arreter(root: Path, run_id: str) -> dict:
    """Arrêt SIGNÉ : ne s'exécute que si le run_id fourni == identité active. N'arrête QUE le labo (jamais le main)."""
    ident = _identite_active(Path(root))
    if not ident:
        return {"arret": "AUCUN_RUN_ACTIF"}
    if run_id != ident.get("run_id"):
        return {"arret": "REFUSE", "motif": "run_id non signé", "attendu": ident.get("run_id")}
    try:
        (_run_root(Path(root)) / "ACTIVE.json").unlink()
    except OSError:
        pass
    (_run_root(Path(root)) / ("%s.STOP" % run_id)).write_text("stop", encoding="utf-8")
    return {"arret": "OK", "run_id": run_id, "note": "labo seul ; main intact"}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    try:
        with p.open("rb") as f:
            for buf in iter(lambda: f.read(1 << 20), b""):
                h.update(buf)
    except OSError:
        return "?"
    return h.hexdigest()


def finaliser(root: Path) -> dict:
    """Scelle : manifest SHA256 de tous les résultats + rapport racine RAPPORT-RECHERCHE-14H.md."""
    ident = _identite_active(Path(root)) or {}
    rundir = Path(ident.get("rundir") or (_run_root(Path(root)) / "dernier"))
    manifeste = {}
    if rundir.exists():
        for f in sorted(rundir.rglob("*")):
            if f.is_file():
                manifeste[str(f.relative_to(rundir))] = {"sha256": _sha256(f), "octets": f.stat().st_size}
    (rundir / "manifeste" / "SHA256_MANIFEST.json").parent.mkdir(parents=True, exist_ok=True)
    (rundir / "manifeste" / "SHA256_MANIFEST.json").write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
    rapport = Path(root) / "RAPPORT-RECHERCHE-14H.md"
    rapport.write_text(_rapport_md(ident, manifeste), encoding="utf-8")
    try:
        (_run_root(Path(root)) / "ACTIVE.json").unlink()
    except OSError:
        pass
    return {"finalisation": "OK", "rapport": str(rapport), "fichiers_scelles": len(manifeste)}


def _rapport_md(ident: dict, manifeste: dict) -> str:
    return ("# RAPPORT-RECHERCHE-14H\n\n"
            "run_id : %s\nT0 : %s\nMécanismes figés : %s\n\n"
            "Fichiers scellés : %d (manifest SHA256).\n\n"
            "> Rapport détaillé (couverture, essais comptabilisés, A/B/C, PnL/ROI nets, PF, DD, capacité,\n"
            "> maker/taker, stress, candidats robustes, KILL exacts, données manquantes, plan de demain)\n"
            "> généré par le moteur de mesure à H14. Sécurité : 0 ordre réel, 0 argent réel.\n"
            % (ident.get("run_id"), ident.get("t0_wall_ms"), ", ".join(ident.get("mecanismes") or []), len(manifeste)))


def _phase_debut_wall_ms(ident: dict, phase: str) -> int:
    for n, d, _f in PHASES:
        if n == phase:
            return int(ident["t0_wall_ms"] + d * 1000)
    return int(ident["t0_wall_ms"])


def boucle_mesure(root: Path, *, intervalle_s: float = 600.0, max_cycles: int | None = None) -> dict:
    """Boucle 14 h : mesure la fenêtre de la phase courante, append au trial ledger, gèle les finalistes à
    la fin de A, finalise à H14. Idempotente/repriseable (relit ACTIVE.json). Arrêt propre sur fichier STOP."""
    root = Path(root)
    ident = _identite_active(root)
    if not ident:
        return {"boucle": "AUCUN_RUN_ACTIF"}
    from recherche_14h_mecanismes import mesurer_phase  # réutilise le moteur de mesure
    try:                                                 # MAINTIEN WINDOWS ÉVEILLÉ pendant les 14 h
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
    except Exception:  # noqa: BLE001
        pass
    rundir = Path(ident["rundir"])
    stop = _run_root(root) / ("%s.STOP" % ident["run_id"])
    ledger = rundir / "ledger" / "trials.jsonl"
    cycles = 0
    while True:
        if stop.exists() or _identite_active(root) is None:
            return {"boucle": "ARRET_SIGNE", "cycles": cycles}
        elapsed = time.time() - ident["t0_wall_ms"] / 1000.0
        if elapsed >= DUREE_TOTALE_S:
            fin = finaliser(root)
            return {"boucle": "TERMINEE_H14", "cycles": cycles, **fin}
        phase = phase_courante(elapsed)
        if phase.startswith(("A_", "B_", "C_")):     # on ne mesure pas pendant les embargos
            deb = _phase_debut_wall_ms(ident, phase)
            res = mesurer_phase(root, t_min_ms=deb, t_max_ms=int(time.time() * 1000))
            ligne = {"ts_ms": int(time.time() * 1000), "elapsed_h": round(elapsed / 3600.0, 3),
                     "phase": phase, "resultats": res}
            try:
                with ledger.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            except OSError:
                pass
            # GEL des finalistes à la 1re mesure de B (fin de A) : top-10 mécanismes par n×|net| en A
            fin_fin = rundir / "resultats" / "finalistes.json"
            if phase.startswith("B_") and not fin_fin.exists():
                _geler_finalistes(rundir, ledger)
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            return {"boucle": "MAX_CYCLES", "cycles": cycles}
        time.sleep(intervalle_s)


def _geler_finalistes(rundir: Path, ledger: Path) -> None:
    """Fige ≤10 mécanismes finalistes d'après la phase A (aucun tuning après). Robustesse = n × |net médian|."""
    scores = {}
    try:
        for l in ledger.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            if not r.get("phase", "").startswith("A_"):
                continue
            for meca, v in (r.get("resultats") or {}).items():
                if v.get("n", 0) >= 5 and v.get("net_median_bps") is not None:
                    scores[meca] = max(scores.get(meca, 0.0), v["n"] * abs(v["net_median_bps"]))
    except (OSError, ValueError):
        pass
    finalistes = [m for m, _s in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)][:MAX_FINALISTES]
    (rundir / "resultats" / "finalistes.json").write_text(
        json.dumps({"finalistes": finalistes, "fige_apres": "A_DECOUVERTE", "max": MAX_FINALISTES},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Orchestrateur recherche 14h (lecture seule, isolé).")
    ap.add_argument("cmd", choices=["precheck", "start", "status", "resume", "stop", "finalize", "dry-run", "boucle"])
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--run-id", default="")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.cmd == "precheck":
        out = precheck(root)
    elif a.cmd == "dry-run":
        out = demarrer(root, dry_run=True)
    elif a.cmd == "start":
        out = demarrer(root, dry_run=False)
    elif a.cmd == "status":
        out = statut(root)
    elif a.cmd == "resume":
        out = {"resume": "IDEMPOTENT", **statut(root)}     # reprise = relire l'identité, aucun doublon
    elif a.cmd == "stop":
        out = arreter(root, a.run_id)
    elif a.cmd == "finalize":
        out = finaliser(root)
    elif a.cmd == "boucle":
        out = boucle_mesure(root)
    else:
        out = {"erreur": "commande inconnue"}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
