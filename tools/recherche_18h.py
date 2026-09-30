"""ORCHESTRATEUR du labo de recherche AUTONOME 18 h (Flo 26/07).

Chaîne NOUVELLE et ISOLÉE (n'altère JAMAIS le 14 h ni ses hashes). Écrit uniquement sous
runtime/research_lab/overnight_18h/<run_id>/. Réutilise l'infra testée : isolation, validation (DSR/PBO/WF),
execution_paper, recherche_14h_mecanismes.mesurer_phase (moteur causal), + les modules 18 h dédiés
(config, securite, catalogue, validation, mecanismes, replay, rapport).

Sous-commandes : dry-run · start · status · watch · resume · stop <run_id> · finalize · boucle.

Objectif directeur : chercher LARGE l'edge net ultra-positif (familles × horizons × coins × régimes) puis
RENFORCER les survivants — sans JAMAIS fabriquer un gain. PAPER-ONLY / READ-ONLY : 0 exchange, 0 signature,
0 clé, 0 ordre, 0 executor. Aucun résultat n'autorise un ordre réel.

PHASES (secondes depuis T0, total 18 h) :
  PREFLIGHT [0;1h) · DISCOVERY [1h;6h) · DEDUP_FREEZE [6h;7h) · VALIDATION [7h;11h) · AUDIT [11h;12h)
  · HOLDOUT_FORWARD [12h;17h) · FINALIZE [17h;18h].
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.research_parallel import isolation as ISO  # noqa: E402
import config_18h as CFG  # noqa: E402
import securite_18h as SEC  # noqa: E402

RUN_ROOT_REL = ISO.LAB_REL / "overnight_18h"
DUREE_TOTALE_S = 18 * 3600
PHASES = (
    ("PREFLIGHT", 0, 1 * 3600),
    ("DISCOVERY", 1 * 3600, 6 * 3600),
    ("DEDUP_FREEZE", 6 * 3600, 7 * 3600),
    ("VALIDATION", 7 * 3600, 11 * 3600),
    ("AUDIT", 11 * 3600, 12 * 3600),
    ("HOLDOUT_FORWARD", 12 * 3600, 17 * 3600),
    ("FINALIZE", 17 * 3600, 18 * 3600),
)
MECANISMES = ("OFI_TOP1", "OFI_TOP5", "OFI_TOP20", "QUEUE_MICROPRICE", "LIQUIDITY_VACUUM",
              "HL_ABSORPTION_NATIVE", "TRADE_SWEEP_BURST", "OI_VEL_ACCEL_PRICE_FUNDING",
              "FUNDING_CLOCK_DIVERGENCE", "LIQUIDATION_CASCADE_DEPTH")
CRIT = {"min_episodes": 30, "pf_min": 1.2, "dsr_min": 0.95, "pbo_max": 0.20, "cout_stress_pct": 50}


def _run_root(root: Path) -> Path:
    return Path(root) / RUN_ROOT_REL


def _active_path(root: Path) -> Path:
    return _run_root(root) / "ACTIVE.json"


def _identite_active(root: Path) -> dict | None:
    try:
        return json.loads(_active_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def phase_courante(elapsed_s: float) -> str:
    for nom, deb, fin in PHASES:
        if deb <= elapsed_s < fin:
            return nom
    return "TERMINE" if elapsed_s >= DUREE_TOTALE_S else "PREFLIGHT"


def _code_sha() -> str:
    """Empreinte du CODE 18 h (tous les tools/*_18h.py) pour le manifeste — reproductibilité."""
    h = hashlib.sha256()
    for p in sorted((RACINE / "tools").glob("*18h*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ─────────────────────────── dry-run (preflight sans chrono) ───────────────────────────
def dry_run(root: Path) -> dict:
    """Precheck NON bloquant sur chrono : sécurité, disque, catalogue (aperçu), ressources, partitions
    (aperçu), registre. Rend un JSON PASS/FAIL avec le détail — ne démarre AUCUN run."""
    root = Path(root)
    rap = {"commande": "dry-run", "ts": int(time.time() * 1000)}
    sec = SEC.auditer(root)
    rap["securite"] = {"securise": sec["securise"], "fichiers_scannes": sec["fichiers_scannes"],
                       "findings": sec["findings"][:20]}
    disk_ok, disk_msg = CFG.disque_ok(str(root))
    rap["disque"] = {"ok": disk_ok, "detail": disk_msg}
    rap["ressources"] = CFG.limites(str(root))
    # aperçu catalogue RAPIDE (comptage borné, sans SHA ni parse profond, n'écrit rien)
    try:
        import catalogue_archives_18h as CAT
        rap["catalogue_apercu"] = CAT.apercu_rapide(root)
    except Exception as e:  # noqa: BLE001
        rap["catalogue_apercu"] = {"erreur": str(e)[:160]}
    rap["phases_18h"] = [{"nom": n, "debut_h": d / 3600, "fin_h": f / 3600} for n, d, f in PHASES]
    rap["mecanismes"] = list(MECANISMES)
    rap["criteres"] = CRIT
    rap["code_sha"] = _code_sha()
    rap["PASS"] = bool(sec["securise"] and disk_ok)
    rap["securite_ligne"] = "0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · 0 depot/retrait"
    return rap


# ─────────────────────────── start ───────────────────────────
def flux_croissent(root: Path) -> dict:
    """P5 — les collecteurs live grossissent-ils ? Lit deux fois (à 2 s) les heartbeats microstructure/context
    et exige une croissance du compteur de messages + des timestamps frais. Rend {ok, detail}."""
    root = Path(root)
    def lire():
        out = {}
        for nom, rel in (("micro", "runtime/research_lab/micro_heartbeat.json"),
                         ("ctx", "runtime/research_lab/heartbeat.json")):
            try:
                out[nom] = json.loads((root / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                out[nom] = None
        return out
    a = lire()
    time.sleep(2.0)
    b = lire()
    def compteur(d):
        if not d:
            return None
        for k in ("messages", "events", "n_messages", "count", "ticks"):
            if isinstance(d.get(k), (int, float)):
                return d[k]
        return None
    croit = False
    detail = {}
    for nom in ("micro", "ctx"):
        ca, cb = compteur(a.get(nom)), compteur(b.get(nom))
        detail[nom] = {"avant": ca, "apres": cb}
        if ca is not None and cb is not None and cb > ca:
            croit = True
    return {"ok": croit, "detail": detail}


def demarrer(root: Path, *, exiger_flux: bool = True) -> dict:
    """Precheck bloquant puis création du run (chrono démarre SEULEMENT si PASS). Écrit run_identity.json +
    ACTIVE.json, catalogue les archives, scelle les partitions, initialise le registre. P5 : refuse de
    démarrer si les flux live ne croissent pas (sauf exiger_flux=False pour les tests)."""
    root = Path(root)
    if _identite_active(root) is not None:
        return {"start": "DEJA_ACTIF", "run_id": _identite_active(root).get("run_id")}
    dr = dry_run(root)
    if not dr["PASS"]:
        return {"start": "PRECHECK_ECHEC", "raisons": {"securite": dr["securite"]["securise"], "disque": dr["disque"]}}
    if exiger_flux:
        fx = flux_croissent(root)
        if not fx["ok"]:
            return {"start": "FLUX_NE_CROISSENT_PAS", "detail": fx["detail"],
                    "aide": "les collecteurs live doivent tourner et grossir avant le chrono (P5)"}
    run_id = "r18h-" + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:12]
    rundir = _run_root(root) / run_id
    for sd in ("catalogue", "partitions", "ledger", "resultats", "manifeste", "results", "logs"):
        (rundir / sd).mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ident = {
        "run_id": run_id, "pid": os.getpid(), "t0_wall_ms": int(t0 * 1000), "t0_mono_ns": time.monotonic_ns(),
        "fin_prevue_wall_ms": int((t0 + DUREE_TOTALE_S) * 1000), "duree_totale_s": DUREE_TOTALE_S,
        "phases": [{"nom": n, "debut_s": d, "fin_s": f} for n, d, f in PHASES],
        "mecanismes": list(MECANISMES), "criteres": CRIT, "rundir": str(rundir),
        "config": CFG.limites(str(root)), "code_sha": _code_sha(),
        "read_only": True, "real_execution": False, "objectif": "edge net paper ultra-positif, honnete, apres tous couts",
    }
    (rundir / "run_identity.json").write_text(json.dumps(ident, ensure_ascii=False, indent=1), encoding="utf-8")
    _active_path(root).write_text(json.dumps(ident, ensure_ascii=False, indent=1), encoding="utf-8")
    # catalogue réel + partitions scellées
    try:
        import catalogue_archives_18h as CAT
        import validation_18h as V18
        resume = CAT.cataloguer(root, rundir)
        # bornes temporelles à partir des sources parsées
        ts_min = min((e for e in _cat_ts(rundir, "min")), default=t0 * 1000 - DUREE_TOTALE_S * 1000)
        ts_max = max((e for e in _cat_ts(rundir, "max")), default=t0 * 1000)
        split = V18.partitions_temporelles(ts_min, ts_max, horizon_max_ms=3_600_000.0)
        V18.sceller_split(rundir, split)
        ident["catalogue_resume"] = resume
    except Exception as e:  # noqa: BLE001
        ident["catalogue_erreur"] = str(e)[:160]
    (rundir / "ledger" / "trials_preregistered.jsonl").touch()
    (rundir / "ledger" / "trials_results.jsonl").touch()
    (rundir / "ledger" / "trials_superseded.jsonl").touch()
    return {"start": "OK", "actif": True, "run_id": run_id, "rundir": str(rundir),
            "fin_prevue_wall_ms": ident["fin_prevue_wall_ms"], "PRECHECK": "PASS", "code_sha": ident["code_sha"]}


def _cat_ts(rundir: Path, quel: str):
    try:
        cat = json.loads((rundir / "catalogue" / "DATA_CATALOG.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    k = "ts_min" if quel == "min" else "ts_max"
    return [s[k] for s in cat.get("sources", []) if s.get(k) is not None]


# ─────────────────────────── status / watch ───────────────────────────
def statut(root: Path) -> dict:
    root = Path(root)
    ident = _identite_active(root)
    if not ident:
        return {"actif": False}
    elapsed = time.time() - ident["t0_wall_ms"] / 1000.0
    return {"actif": elapsed < DUREE_TOTALE_S, "run_id": ident["run_id"], "pid": ident.get("pid"),
            "elapsed_h": round(elapsed / 3600.0, 2), "phase": phase_courante(elapsed),
            "reste_h": round(max(0.0, (DUREE_TOTALE_S - elapsed) / 3600.0), 2),
            "fin_prevue_wall_ms": ident.get("fin_prevue_wall_ms"), "rundir": ident.get("rundir")}


def _lire_heartbeat(rundir: Path) -> dict:
    try:
        return json.loads((Path(rundir) / "logs" / "heartbeat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def watch_ecran(root: Path) -> str:
    """UN écran lisible (chaîne) — la boucle .cmd le rafraîchit toutes les 5 s. Avant le gel des finalistes,
    n'affiche QUE 'resultats exploratoires — non valides'."""
    st = statut(root)
    if not st.get("actif") and not st.get("run_id"):
        return "HYPERSMART 18H — aucun run actif.\n"
    ident = _identite_active(root) or {}
    rundir = Path(ident.get("rundir", "."))
    c = _compteurs(rundir) if rundir.exists() else {}
    hb = _lire_heartbeat(rundir)
    import time as _t
    fin_iso = _t.strftime("%d/%m/%Y %H:%M", _t.localtime((ident.get("fin_prevue_wall_ms") or 0) / 1000.0)) if ident.get("fin_prevue_wall_ms") else "?"
    fige = phase_courante((time.time() - ident.get("t0_wall_ms", time.time() * 1000) / 1000.0)) in (
        "AUDIT", "HOLDOUT_FORWARD", "FINALIZE")
    lignes = [
        "==========================================================",
        " HYPERSMART — RECHERCHE AUTONOME 18 H — PAPER ONLY",
        "==========================================================",
        " Run             : %s" % st.get("run_id"),
        " Etat            : %s   Phase : %s" % (("ACTIF" if st.get("actif") else "TERMINE"), st.get("phase")),
        " Ecoule          : %.2f h   Restant : %.2f h" % (st.get("elapsed_h", 0), st.get("reste_h", 0)),
        " Fin prevue      : %s" % fin_iso,
        "",
        " DONNEES (utilisation reelle)",
        " Sources detectees/utilisees/exclues : %s / %s / %s" % (c.get("sources_detectees", 0), c.get("sources_utilisees", 0), c.get("sources_exclues", 0)),
        " Events archives utilises : %s   dedup : %s   gaps : %s" % (c.get("events_archives", 0), c.get("events_dedup", 0), c.get("gaps", 0)),
        "",
        " RECHERCHE (compteurs RÉELS depuis les fichiers)",
        " Trials preregistres : %s" % c.get("preregistres", 0),
        " Resultats (terminaux): %s" % c.get("resultats", 0),
        " Fast-screen         : %s" % c.get("fast_screen", 0),
        " Exact replays       : %s" % c.get("exact_replays", 0),
        " Candidats vivants   : %s" % c.get("candidats_vivants", 0),
        " Finalistes (PASS)   : %s" % c.get("finalistes", 0),
        " Forward paper events: %s" % c.get("forward_events", 0),
        "",
        " Derniere action     : %s (cycle %s)" % (hb.get("phase", "?"), hb.get("cycle", 0)),
        " AVANT GEL : resultats exploratoires — NON VALIDES" if not fige else " APRES GEL : archive_validation / archive_holdout / forward_paper separes",
        "",
        " SECURITE        : 0 ordre reel · 0 cle · 0 signature · 0 executor",
        "==========================================================",
    ]
    return "\n".join(lignes) + "\n"


# ─────────────────────────── resume / stop / boucle / finalize ───────────────────────────
def reprendre(root: Path) -> dict:
    """Reprise idempotente. P8 : si une boucle vivante détient déjà LOOP_LOCK, NE PAS en lancer une 2e."""
    ident = _identite_active(Path(root))
    if not ident:
        return {"resume": "AUCUN_RUN_ACTIF"}
    rundir = Path(ident["rundir"])
    if loop_lock_actif(rundir):
        return {"resume": "BOUCLE_DEJA_VIVANTE", "run_id": ident["run_id"], "lancer_boucle": False}
    return {"resume": "OK", "run_id": ident["run_id"], "idempotent": True, "lancer_boucle": True}


def stopper(root: Path, run_id: str) -> dict:
    root = Path(root)
    ident = _identite_active(root)
    if not ident:
        return {"stop": "AUCUN_RUN_ACTIF"}
    if ident.get("run_id") != run_id:
        return {"stop": "RUN_ID_NON_CORRESPONDANT", "attendu": ident.get("run_id")}
    (_run_root(root) / ("%s.STOP" % run_id)).write_text("stop", encoding="utf-8")
    return {"stop": "SIGNE", "run_id": run_id}


def battre_coeur(rundir: Path, extra: dict) -> None:
    p = Path(rundir) / "logs" / "heartbeat.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    base = {"ts_ms": int(time.time() * 1000)}
    base.update(extra)
    p.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")


def finaliser(root: Path) -> dict:
    """Scelle : manifeste SHA256 (rapport + code + résultats) + rapport 18 h exhaustif. Clôt ACTIVE.json."""
    root = Path(root)
    ident = _identite_active(root) or {}
    rundir = Path(ident.get("rundir") or (_run_root(root) / "dernier"))
    manifeste = {}
    if rundir.exists():
        for f in sorted(rundir.rglob("*")):
            if f.is_file():
                manifeste[str(f.relative_to(rundir))] = {"sha256": _sha256(f), "octets": f.stat().st_size}
    (rundir / "manifeste").mkdir(parents=True, exist_ok=True)
    # ORDRE P10 : 1) résultats déjà écrits par le pipeline ; 2) RAPPORT ; 3) sécurité ; 4) hashes ; 5) MANIFESTE EN DERNIER.
    etat = "OK"
    try:
        import rapport_18h as RAP
        md = RAP.construire_rapport(rundir, manifeste=None)   # le manifeste final n'existe pas encore (écrit en dernier)
    except Exception as e:  # noqa: BLE001 — une erreur de rapport n'est PAS masquée par 'OK'
        md = "# RAPPORT-RECHERCHE-18H\n\n(rapport PARTIEL — erreur : %s)\n\nSécurité : 0 ordre réel.\n" % (str(e)[:160])
        etat = "FINALIZATION_PARTIAL"
    (root / "RAPPORT-RECHERCHE-18H.md").write_text(md, encoding="utf-8")
    (rundir / ("RAPPORT-RECHERCHE-18H_%s.md" % ident.get("run_id", "run"))).write_text(md, encoding="utf-8")
    sec = SEC.auditer(root)                                   # re-scan sécurité à la finalisation
    if not sec["securise"]:
        etat = "FINALIZATION_FAILED"
    # hashes de TOUS les livrables (rapport inclus) PUIS manifeste final en dernier
    manifeste = {}
    for f in sorted(rundir.rglob("*")):
        if f.is_file() and f.name != "SHA256_MANIFEST_FINAL.json":
            manifeste[str(f.relative_to(rundir))] = {"sha256": _sha256(f), "octets": f.stat().st_size}
    manifeste["__RAPPORT_RACINE__/RAPPORT-RECHERCHE-18H.md"] = {
        "sha256": _sha256(root / "RAPPORT-RECHERCHE-18H.md"), "octets": (root / "RAPPORT-RECHERCHE-18H.md").stat().st_size}
    (rundir / "manifeste" / "SHA256_MANIFEST_FINAL.json").write_text(
        json.dumps({"etat": etat, "code_sha": _code_sha(), "securise": sec["securise"],
                    "contient_rapport": True, "fichiers": manifeste}, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        _active_path(root).unlink()
    except OSError:
        pass
    return {"finalisation": etat, "fichiers_scelles": len(manifeste), "securise": sec["securise"],
            "rapport": str(root / "RAPPORT-RECHERCHE-18H.md")}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ─────────────────────────── LOOP_LOCK (P8) ───────────────────────────
def _loop_lock_path(rundir: Path) -> Path:
    return Path(rundir) / "logs" / "LOOP_LOCK.json"


def _proc_vivant(pid: int, start_iso: str | None) -> bool:
    try:
        import psutil  # type: ignore
        if not psutil.pid_exists(pid):
            return False
        if start_iso is not None:
            return abs(psutil.Process(pid).create_time() - float(start_iso)) < 2.0   # anti-PID réutilisé
        return True
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)                      # POSIX : le signal 0 teste l'existence
            return True
        except (OSError, ProcessLookupError):
            return False


def acquerir_loop_lock(rundir: Path) -> tuple[bool, dict]:
    """Verrou de boucle ATOMIQUE. Refuse si une boucle vivante détient déjà le verrou (P8 : resume ne lance
    jamais une 2e boucle). Rend (obtenu, info)."""
    import uuid
    p = _loop_lock_path(rundir)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if _proc_vivant(int(cur.get("loop_pid", -1)), cur.get("process_start_time")):
                return False, {"lock": "DEJA_DETENU", "loop_pid": cur.get("loop_pid")}
        except (ValueError, OSError):
            pass
    start = None
    try:
        import psutil  # type: ignore
        start = psutil.Process(os.getpid()).create_time()
    except Exception:  # noqa: BLE001
        pass
    info = {"loop_pid": os.getpid(), "process_start_time": start, "worker_token": uuid.uuid4().hex[:12],
            "ts_ms": int(time.time() * 1000)}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)                          # écriture atomique
    return True, info


def loop_lock_actif(rundir: Path) -> bool:
    p = _loop_lock_path(rundir)
    if not p.exists():
        return False
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False
    return _proc_vivant(int(cur.get("loop_pid", -1)), cur.get("process_start_time"))


def _corpus_pour_run(root: Path):
    import pipeline_18h as PL
    return PL.corpus_depuis_archives(root)


def _executer_travail(root: Path, ident: dict, rundir: Path) -> dict:
    """Exécute le PIPELINE RÉEL sur TOUTES les données (LOT18H-DATA-COMPLETE) : catalogue complet → corpus
    canonique consommé → discovery→freeze→validation→holdout→forward→reconcile → logs → lignée → CSVs.
    Idempotent : ne relance pas si pipeline_resume.json existe déjà."""
    import pipeline_18h as PL
    if (rundir / "resultats" / "pipeline_resume.json").exists():
        return json.loads((rundir / "resultats" / "pipeline_resume.json").read_text(encoding="utf-8"))
    return PL.executer_pipeline_donnees_completes(root, rundir, code_sha=ident.get("code_sha", "?"))


def _compteurs(rundir: Path) -> dict:
    import registre_18h as REG
    c = REG.compter(rundir)
    resume = {}
    try:
        resume = json.loads((rundir / "resultats" / "pipeline_resume.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    fwd = rundir / "ledger" / "forward_paper.jsonl"
    n_fwd = sum(1 for _ in fwd.read_text(encoding="utf-8").splitlines()) if fwd.exists() else 0
    acc = resume.get("accounting", {})
    cc = resume.get("corpus_comptes", {})
    la = resume.get("log_analyse", {})
    return {"preregistres": c["preregistres"], "resultats": c["resultats"], "superseded": c["superseded"],
            "fast_screen": resume.get("n_fast_screen", 0), "exact_replays": resume.get("n_exact_replays", 0),
            "candidats_vivants": resume.get("n_survivants", 0), "finalistes": resume.get("n_pass", 0),
            "forward_events": n_fwd,
            "sources_detectees": acc.get("n_total_detected", 0), "sources_utilisees": acc.get("n_parsed", 0),
            "sources_exclues": acc.get("n_excluded", 0), "events_archives": cc.get("utilises", 0),
            "events_dedup": cc.get("dedup", 0), "gaps": la.get("n_gaps", 0)}


def boucle(root: Path, *, intervalle_s: float = 60.0, max_cycles: int | None = None) -> dict:
    """Boucle 18 h : phase-aware, LOOP_LOCK (une seule boucle), heartbeat avec COMPTEURS RÉELS, exécute le
    PIPELINE (pas seulement un heartbeat), reprise idempotente, finalise à H18. STOP propre. Windows éveillé."""
    root = Path(root)
    ident = _identite_active(root)
    if not ident:
        return {"boucle": "AUCUN_RUN_ACTIF"}
    rundir = Path(ident["rundir"])
    obtenu, info = acquerir_loop_lock(rundir)
    if not obtenu:
        return {"boucle": "LOCK_DEJA_DETENU", **info}   # P8 : pas de 2e boucle
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)
    except Exception:  # noqa: BLE001
        pass
    stop = _run_root(root) / ("%s.STOP" % ident["run_id"])
    cycles = 0
    while True:
        if stop.exists() or _identite_active(root) is None:
            return {"boucle": "ARRET_SIGNE", "cycles": cycles}
        elapsed = time.time() - ident["t0_wall_ms"] / 1000.0
        if elapsed >= DUREE_TOTALE_S:
            return {"boucle": "TERMINEE_H18", "cycles": cycles, **finaliser(root)}
        phase = phase_courante(elapsed)
        # 🔴 TRAVAIL RÉEL : dès DISCOVERY, exécuter le pipeline (idempotent). La boucle PRODUIT des trials.
        travail = {}
        if phase not in ("PREFLIGHT",):
            try:
                travail = _executer_travail(root, ident, rundir)
            except Exception as e:  # noqa: BLE001 — un échec de travail est journalisé, la boucle survit (watchdog)
                (rundir / "logs" / "erreurs.jsonl").open("a", encoding="utf-8").write(
                    json.dumps({"ts_ms": int(time.time() * 1000), "phase": phase, "erreur": str(e)[:200]}) + "\n")
        battre_coeur(rundir, {"phase": phase, "elapsed_h": round(elapsed / 3600.0, 3), "cycle": cycles,
                              **_compteurs(rundir)})
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            return {"boucle": "MAX_CYCLES", "cycles": cycles, "phase": phase, "travail": travail}
        time.sleep(intervalle_s)


def _cli():
    ap = argparse.ArgumentParser(description="Labo de recherche autonome 18 h (paper-only)")
    ap.add_argument("commande", choices=["dry-run", "start", "status", "watch", "resume", "stop", "finalize", "boucle"])
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--intervalle", type=float, default=60.0)
    ap.add_argument("--max-cycles", type=int, default=None)
    a = ap.parse_args()
    root = RACINE
    if a.commande == "dry-run":
        print(json.dumps(dry_run(root), ensure_ascii=False, indent=1))
    elif a.commande == "start":
        print(json.dumps(demarrer(root), ensure_ascii=False, indent=1))
    elif a.commande == "status":
        print(json.dumps(statut(root), ensure_ascii=False, indent=1))
    elif a.commande == "watch":
        print(watch_ecran(root))
    elif a.commande == "resume":
        print(json.dumps(reprendre(root), ensure_ascii=False, indent=1))
    elif a.commande == "stop":
        print(json.dumps(stopper(root, a.run_id or ""), ensure_ascii=False, indent=1))
    elif a.commande == "finalize":
        print(json.dumps(finaliser(root), ensure_ascii=False, indent=1))
    elif a.commande == "boucle":
        print(json.dumps(boucle(root, intervalle_s=a.intervalle, max_cycles=a.max_cycles), ensure_ascii=False))


if __name__ == "__main__":
    _cli()
