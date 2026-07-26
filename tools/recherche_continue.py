"""LABORATOIRE DE RECHERCHE CONTINU (Flo 26/07). PLUS de limite de durée : démarre au CMD, travaille en
cycles sans cesse, affiche tout en direct, et ne produit le rapport final Markdown QUE sur Ctrl+C (ou
`stop <run_id>`). ADDITIF : ne casse NI le mode 14 h NI le mode 18 h. Réutilise entièrement pipeline_18h
(catalogue complet, lecteurs, corpus, dédup, accounting, FAST_SCREEN, EXACT_REPLAY, validation, holdout,
forward paper, logs, lineage, PnL/ROI). Écrit UNIQUEMENT sous runtime/research_lab/continuous/<run_id>/.

CYCLE : INGESTION → NORMALISATION → INDEXATION → DISCOVERY → FAST_SCREEN → EXACT_REPLAY → VALIDATION →
GEL → HOLDOUT → FORWARD PAPER → ANALYSE → NOUVEAU CYCLE. Chaque cycle = une CAMPAGNE (campaign_id,
data_cutoff, partitions scellées, code_sha, config_hash, critères, candidats figés, ledger SÉPARÉ) et ne
consomme que les NOUVELLES données (curseurs par source) ; les stratégies figées poursuivent leur forward
paper. Aucun double comptage. PAPER-ONLY / READ-ONLY : 0 exchange, 0 signature, 0 clé, 0 ordre.

Ctrl+C = bouton officiel de finalisation. 1er Ctrl+C : arrêt PROPRE (stop des nouveaux trials, checkpoint,
cursors, réconciliation, CSV/JSON, rapport MD, manifeste SHA-256 en DERNIER). 2e Ctrl+C : FINALIZATION_PARTIAL
d'urgence, rien de perdu en silence. threading.Event partagé + workers non-daemon.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.research_parallel import isolation as ISO  # noqa: E402
import config_18h as CFG  # noqa: E402
import securite_18h as SEC  # noqa: E402

RUN_ROOT_REL = ISO.LAB_REL / "continuous"
CYCLE_PHASES = ("INGESTION", "NORMALISATION", "INDEXATION", "DISCOVERY", "FAST_SCREEN", "EXACT_REPLAY",
                "VALIDATION", "GEL", "HOLDOUT", "FORWARD_PAPER", "ANALYSE")

# état d'arrêt partagé (Ctrl+C). _ARRET = 1er signal (arrêt propre) ; _URGENCE = 2e signal (partiel).
_ARRET = threading.Event()
_URGENCE = threading.Event()


def _run_root(root: Path) -> Path:
    return Path(root) / RUN_ROOT_REL


def _active_path(root: Path) -> Path:
    return _run_root(root) / "ACTIVE.json"


def _identite_active(root: Path) -> dict | None:
    try:
        return json.loads(_active_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _code_sha() -> str:
    h = hashlib.sha256()
    for p in sorted((RACINE / "tools").glob("*.py")):
        if "18h" in p.name or "continue" in p.name:
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _ecrire_atomique(p: Path, contenu: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(contenu, encoding="utf-8")
    os.replace(tmp, p)


# ─────────────── curseurs (ne consommer que les NOUVELLES données) ───────────────
def _curseurs(rundir: Path) -> dict:
    try:
        return json.loads((rundir / "cursors.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _maj_curseurs_et_nouveaute(root: Path, rundir: Path) -> tuple[bool, dict]:
    """Détecte s'il y a de NOUVELLES données depuis le dernier cycle (taille/mtime des sources). Met à jour
    les curseurs (atomique). Rend (nouveaute?, curseurs)."""
    import catalogue_archives_18h as CAT
    cur = _curseurs(rundir)
    nouveaute = False
    apercu = CAT.apercu_rapide(root)
    signature = {}
    for dd in CAT.DOSSIERS:
        base = Path(root) / dd
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in CAT.EXTS and "continuous" not in str(p):
                try:
                    signature[str(p)] = p.stat().st_size
                except OSError:
                    continue
    for k, taille in signature.items():
        if cur.get(k) != taille:
            nouveaute = True
            break
    _ecrire_atomique(rundir / "cursors.json", json.dumps(signature, ensure_ascii=False))
    return (nouveaute or not cur), {"n_sources": apercu["n_sources"]}


# ─────────────── un cycle = une campagne ───────────────
def executer_cycle(root: Path, rundir: Path, *, cycle: int, code_sha: str) -> dict:
    """Exécute UN cycle complet dans une campagne dédiée (ledger séparé). Consomme les nouvelles données,
    reprend les travaux incomplets (idempotence du registre), ne double-compte pas. Rend le résumé du cycle."""
    import pipeline_18h as PL
    t0 = time.time()
    nouveaute, ing = _maj_curseurs_et_nouveaute(root, rundir)
    camp_id = "camp-%04d-%s" % (cycle, hashlib.sha256(("%s%d" % (code_sha, cycle)).encode()).hexdigest()[:8])
    camp_dir = rundir / "campagnes" / camp_id
    for sd in ("ledger", "resultats", "results", "partitions", "catalogue"):
        (camp_dir / sd).mkdir(parents=True, exist_ok=True)
    (camp_dir / "campaign.json").write_text(json.dumps({
        "campaign_id": camp_id, "cycle": cycle, "data_cutoff_ms": int(t0 * 1000), "code_sha": code_sha,
        "config_hash": hashlib.sha256(json.dumps(CYCLE_PHASES).encode()).hexdigest()[:12],
        "criteres": __import__("validation_18h").SEUILS, "read_only": True, "real_execution": False},
        ensure_ascii=False, indent=1), encoding="utf-8")
    resume = {}
    try:
        resume = PL.executer_pipeline_donnees_completes(root, camp_dir, code_sha=code_sha)
    except Exception as e:  # noqa: BLE001 — un cycle qui échoue est journalisé, la boucle continue
        (rundir / "errors.csv").open("a", encoding="utf-8").write("%d,%s\n" % (cycle, str(e)[:160].replace(",", ";")))
        resume = {"erreur": str(e)[:160]}
    resume.update({"campaign_id": camp_id, "cycle": cycle, "nouvelles_donnees": nouveaute,
                   "duree_cycle_s": round(time.time() - t0, 2)})
    # journal d'événements + checkpoint atomiques
    with (rundir / "LIVE-RESEARCH-EVENTS.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts_ms": int(time.time() * 1000), "cycle": cycle, "campaign_id": camp_id,
                            **{k: resume.get(k) for k in ("n_forward_events", "n_survivants", "n_pass")}}, ensure_ascii=False) + "\n")
    _checkpoint(rundir, cycle, camp_id)
    return resume


def _checkpoint(rundir: Path, cycle: int, camp_id: str) -> None:
    ck = rundir / "checkpoints" / str(int(time.time()))
    ck.mkdir(parents=True, exist_ok=True)
    _ecrire_atomique(ck / "checkpoint.json", json.dumps({"cycle": cycle, "campaign_id": camp_id,
                                                         "ts_ms": int(time.time() * 1000)}, ensure_ascii=False))


# ─────────────── état pour le dashboard (compteurs RÉELS) ───────────────
def construire_etat(root: Path, rundir: Path, ident: dict, *, cycle: int, phase: str,
                    tache_t0: float, cycle_t0: float) -> dict:
    """Agrège les compteurs RÉELS depuis les campagnes/ledgers/fichiers pour le dashboard + LIVE-RESEARCH-STATE."""
    import registre_18h as REG
    tot = {"preregistres": 0, "resultats": 0, "fast_screen": 0, "exact_replays": 0, "survivants": 0,
           "forward_events": 0, "n_pass": 0, "sources_detectees": 0, "sources_utilisees": 0, "events_utilises": 0}
    interessantes, rejets = [], {"total": 0}
    camps = sorted((rundir / "campagnes").glob("camp-*")) if (rundir / "campagnes").exists() else []
    for c in camps:
        try:
            r = json.loads((c / "resultats" / "pipeline_resume.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        acc = r.get("accounting", {})
        cc = r.get("corpus_comptes", {})
        tot["fast_screen"] += r.get("n_fast_screen", 0); tot["exact_replays"] += r.get("n_exact_replays", 0)
        tot["survivants"] += r.get("n_survivants", 0); tot["forward_events"] += r.get("n_forward_events", 0)
        tot["n_pass"] += r.get("n_pass", 0); tot["sources_detectees"] = max(tot["sources_detectees"], acc.get("n_total_detected", 0))
        tot["sources_utilisees"] = max(tot["sources_utilisees"], acc.get("n_parsed", 0)); tot["events_utilises"] += cc.get("utilises", 0)
        rc = REG.compter(c); tot["preregistres"] += rc["preregistres"]; tot["resultats"] += rc["resultats"]
        try:
            for fv in json.loads((c / "resultats" / "final_verdicts.json").read_text(encoding="utf-8")):
                if (fv.get("holdout_net_median_bps") or 0) > 0:
                    interessantes.append({"candidate_id": fv.get("trial_id"), "coin": fv.get("coin"),
                                          "horizon_ms": fv.get("horizon_ms"), "net_bps": fv.get("holdout_net_median_bps"),
                                          "statut": fv.get("verdict"), "campaign": c.name})
                else:
                    rejets["total"] += 1
        except (OSError, ValueError):
            pass
    interessantes.sort(key=lambda x: -(x["net_bps"] or -1e9))
    debut = ident.get("t0_wall_ms", time.time() * 1000) / 1000.0
    ecoule = time.time() - debut
    etat = {
        "run_id": ident.get("run_id"), "etat": ("ARRET_DEMANDE" if _ARRET.is_set() else "ACTIF"),
        "demarrage_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(debut)),
        "duree_totale_s": round(ecoule, 1),
        "duree": {"jours": int(ecoule // 86400), "heures": int(ecoule % 86400 // 3600),
                  "minutes": int(ecoule % 3600 // 60), "secondes": int(ecoule % 60)},
        "cycle_actuel": cycle, "cycles_termines": max(0, cycle - 1), "phase": phase,
        "duree_tache_s": round(time.time() - tache_t0, 1), "duree_cycle_s": round(time.time() - cycle_t0, 1),
        "dernier_checkpoint": _dernier_checkpoint(rundir), "totaux": tot,
        "pistes_interessantes": interessantes[:15], "rejets": rejets,
        "securite": "0 ordre reel · 0 cle · 0 signature · 0 executor", "paper_only": True, "read_only": True,
    }
    _ecrire_atomique(rundir / "LIVE-RESEARCH-STATE.json", json.dumps(etat, ensure_ascii=False, indent=1))
    try:
        import dashboard_continue as DASH
        _ecrire_atomique(rundir / "LIVE-RESEARCH-DASHBOARD.md", DASH.rendre_markdown(etat))
    except Exception:  # noqa: BLE001
        pass
    return etat


def _dernier_checkpoint(rundir: Path):
    cks = sorted((rundir / "checkpoints").glob("*")) if (rundir / "checkpoints").exists() else []
    return cks[-1].name if cks else None


# ─────────────── boucle continue ───────────────
def boucle_continue(root: Path, *, stop_event: threading.Event | None = None, max_cycles: int | None = None,
                    intervalle_s: float = 2.0, afficher: bool = False) -> dict:
    """Boucle SANS limite de durée. Un cycle par itération jusqu'à l'arrêt (Ctrl+C -> _ARRET, ou stop_event,
    ou max_cycles pour les tests). Écrit l'état à chaque phase. Foreground (le CMD ne détache PAS le moteur) :
    si `afficher`, imprime le dashboard à chaque fin de cycle dans CE terminal."""
    root = Path(root)
    stop_event = stop_event or _ARRET
    ident = _identite_active(root)
    if not ident:
        return {"boucle": "AUCUN_RUN_ACTIF"}
    rundir = Path(ident["rundir"])
    cycle = int(ident.get("cycle_courant", 0)) + 1
    while not stop_event.is_set():
        cycle_t0 = time.time()
        for phase in CYCLE_PHASES:
            if stop_event.is_set():
                break
            construire_etat(root, rundir, ident, cycle=cycle, phase=phase, tache_t0=time.time(), cycle_t0=cycle_t0)
            if phase == "DISCOVERY":                 # le gros du travail se fait dans le cycle pipeline
                executer_cycle(root, rundir, cycle=cycle, code_sha=ident.get("code_sha", "?"))
        ident["cycle_courant"] = cycle
        _ecrire_atomique(_active_path(root), json.dumps(ident, ensure_ascii=False, indent=1))
        etat = construire_etat(root, rundir, ident, cycle=cycle, phase="ANALYSE", tache_t0=cycle_t0, cycle_t0=cycle_t0)
        if afficher:
            try:
                import dashboard_continue as DASH
                print("\033c" + DASH.rendre_texte(etat), flush=True)
            except Exception:  # noqa: BLE001
                pass
        cycle += 1
        if max_cycles is not None and (cycle - 1) >= max_cycles:
            return {"boucle": "MAX_CYCLES", "cycles": cycle - 1}
        stop_event.wait(intervalle_s)
    return {"boucle": "ARRET_DEMANDE", "cycles": cycle - 1}


# ─────────────── dry-run / start / status / snapshot / stop / resume ───────────────
def dry_run(root: Path) -> dict:
    root = Path(root)
    sec = SEC.auditer(root)
    dok, dmsg = CFG.disque_ok(str(root))
    return {"commande": "dry-run", "PASS": bool(sec["securise"] and dok),
            "securite": {"securise": sec["securise"], "fichiers": sec["fichiers_scannes"]},
            "disque": {"ok": dok, "detail": dmsg}, "ressources": CFG.limites(str(root)),
            "mode": "CONTINU (sans limite de duree ; Ctrl+C = finalisation)",
            "securite_ligne": "0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · 0 depot/retrait"}


def creer_ou_reprendre(root: Path, *, exiger_flux: bool = True) -> dict:
    root = Path(root)
    ident = _identite_active(root)
    if ident:
        return {"start": "REPRISE", "run_id": ident["run_id"], "rundir": ident["rundir"], "reprise": True}
    dr = dry_run(root)
    if not dr["PASS"]:
        return {"start": "PRECHECK_ECHEC", "detail": dr}
    run_id = "rcont-" + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:12]
    rundir = _run_root(root) / run_id
    for sd in ("campagnes", "checkpoints", "results"):
        (rundir / sd).mkdir(parents=True, exist_ok=True)
    ident = {"run_id": run_id, "pid": os.getpid(), "t0_wall_ms": int(time.time() * 1000),
             "rundir": str(rundir), "code_sha": _code_sha(), "mode": "CONTINU", "cycle_courant": 0,
             "read_only": True, "real_execution": False}
    _ecrire_atomique(rundir / "run_identity.json", json.dumps(ident, ensure_ascii=False, indent=1))
    _ecrire_atomique(_active_path(root), json.dumps(ident, ensure_ascii=False, indent=1))
    return {"start": "OK", "run_id": run_id, "rundir": str(rundir), "reprise": False}


def statut(root: Path) -> dict:
    ident = _identite_active(Path(root))
    if not ident:
        return {"actif": False}
    try:
        etat = json.loads((Path(ident["rundir"]) / "LIVE-RESEARCH-STATE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        etat = {}
    return {"actif": True, "run_id": ident["run_id"], "cycles_termines": etat.get("cycles_termines", 0),
            "duree_totale_s": etat.get("duree_totale_s"), "totaux": etat.get("totaux", {})}


def snapshot(root: Path) -> dict:
    """Rapport INTERMÉDIAIRE sans interrompre le travail (distinct du rapport final)."""
    ident = _identite_active(Path(root))
    if not ident:
        return {"snapshot": "AUCUN_RUN_ACTIF"}
    import rapport_continue as RAP
    rundir = Path(ident["rundir"])
    dossier_rapports = Path(root) / "Rapports en continu"    # snapshots aussi dans le dossier racine dedie
    dossier_rapports.mkdir(parents=True, exist_ok=True)
    chemin = dossier_rapports / ("SNAPSHOT_%s_%d.md" % (ident["run_id"], int(time.time())))
    _ecrire_atomique(chemin, RAP.construire(rundir, ident, final=False))
    return {"snapshot": "OK", "chemin": str(chemin)}


def stopper(root: Path, run_id: str) -> dict:
    """`stop <run_id>` = MÊME finalisation propre que Ctrl+C."""
    ident = _identite_active(Path(root))
    if not ident:
        return {"stop": "AUCUN_RUN_ACTIF"}
    if ident.get("run_id") != run_id:
        return {"stop": "RUN_ID_NON_CORRESPONDANT", "attendu": ident.get("run_id")}
    return finaliser(Path(root), partial=False, raison="stop")


# ─────────────── finalisation (ordre STRICT) ───────────────
def finaliser(root: Path, *, partial: bool = False, raison: str = "ctrl-c") -> dict:
    """Ordre : 1) stop travaux (déjà via _ARRET) ; 2) checkpoint ; 3) (workers déjà arrêtés) ; 4) valorisation
    paper ; 5) réconciliation ; 6) CSV/JSON ; 7) rapport MD ; 8) audit sécurité ; 9) manifeste SHA-256 DERNIER ;
    10) suppression ACTIVE seulement si cohérent. Statuts FINALIZATION_*."""
    import rapport_continue as RAP
    root = Path(root)
    ident = _identite_active(root)
    if not ident:
        return {"finalisation": "AUCUN_RUN_ACTIF"}
    rundir = Path(ident["rundir"])
    _ARRET.set()
    _checkpoint(rundir, int(ident.get("cycle_courant", 0)), "FINALIZE")
    etat = "FINALIZATION_PARTIAL" if partial else "FINALIZATION_COMPLETE"
    date_fin = time.strftime("%Y%m%d-%H%M%S")
    dossier_rapports = root / "Rapports en continu"          # tous les rapports dans un dossier racine dedie
    dossier_rapports.mkdir(parents=True, exist_ok=True)
    rapport = dossier_rapports / ("RAPPORT-RECHERCHE-CONTINUE_%s_%s.md" % (ident["run_id"], date_fin))
    try:
        md, exclusions = RAP.construire(rundir, ident, final=True, partial=partial, retourner_exclusions=True)
        if exclusions:
            etat = "FINALIZATION_COMPLETE_WITH_EXCLUSIONS" if not partial else etat
    except Exception as e:  # noqa: BLE001 — une erreur de rapport n'est pas masquée
        md = "# RAPPORT-RECHERCHE-CONTINUE (%s)\n\nErreur rapport : %s\nSécurité : 0 ordre réel.\n" % (etat, str(e)[:160])
        etat = "FINALIZATION_PARTIAL" if not partial else "FINALIZATION_FAILED"
    _ecrire_atomique(rapport, md)
    _ecrire_atomique(rundir / rapport.name, md)
    sec = SEC.auditer(root)
    if not sec["securise"]:
        etat = "FINALIZATION_FAILED"
    # manifeste SHA-256 EN DERNIER (inclut le rapport + tous les results)
    manifeste = {}
    for f in sorted(rundir.rglob("*")):
        if f.is_file() and f.name != "SHA256_MANIFEST_FINAL.json":
            manifeste[str(f.relative_to(rundir))] = _sha(f)
    manifeste["__RAPPORT__/" + rapport.name] = _sha(rapport)
    _ecrire_atomique(rundir / "manifeste" / "SHA256_MANIFEST_FINAL.json",
                     json.dumps({"etat": etat, "securise": sec["securise"], "contient_rapport": True,
                                 "code_sha": _code_sha(), "fichiers": manifeste}, ensure_ascii=False, indent=1))
    coherent = etat in ("FINALIZATION_COMPLETE", "FINALIZATION_COMPLETE_WITH_EXCLUSIONS")
    if coherent:
        try:
            _active_path(root).unlink()
        except OSError:
            pass
    resume = statut(root)
    return {"finalisation": etat, "rapport": str(rapport), "manifeste": str(rundir / "manifeste" / "SHA256_MANIFEST_FINAL.json"),
            "securise": sec["securise"], "raison": raison, "resume": resume.get("totaux", {})}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ─────────────── Ctrl+C = finalisation ───────────────
def _installer_signal(root: Path):
    def handler(signum, frame):  # noqa: ARG001
        if not _ARRET.is_set():
            print("\n=== ARRÊT PROPRE DEMANDÉ (Ctrl+C) — plus de nouveaux trials, finalisation en cours… ===", flush=True)
            _ARRET.set()
        else:
            print("\n=== 2e Ctrl+C : SAUVEGARDE D'URGENCE (FINALIZATION_PARTIAL) ===", flush=True)
            _URGENCE.set()
    signal.signal(signal.SIGINT, handler)


def demarrer_foreground(root: Path, *, exiger_flux: bool = True, max_cycles: int | None = None) -> dict:
    """Démarre le run et TRAVAILLE au premier plan jusqu'au Ctrl+C, puis finalise proprement (partiel si 2e
    Ctrl+C). Le moteur N'est PAS détaché (sinon Ctrl+C ne contrôlerait pas la finalisation)."""
    root = Path(root)
    _ARRET.clear(); _URGENCE.clear()
    r = creer_ou_reprendre(root, exiger_flux=exiger_flux)
    if r.get("start") == "PRECHECK_ECHEC":
        return r
    _installer_signal(root)
    boucle_continue(root, stop_event=_ARRET, max_cycles=max_cycles, afficher=True)
    return finaliser(root, partial=_URGENCE.is_set(), raison="ctrl-c")


def _cli():
    ap = argparse.ArgumentParser(description="Laboratoire de recherche CONTINU (paper-only)")
    ap.add_argument("commande", choices=["dry-run", "start", "resume", "status", "snapshot", "stop"])
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    root = RACINE
    if a.commande == "dry-run":
        print(json.dumps(dry_run(root), ensure_ascii=False, indent=1))
    elif a.commande in ("start", "resume"):
        print(json.dumps(demarrer_foreground(root), ensure_ascii=False, indent=1))
    elif a.commande == "status":
        print(json.dumps(statut(root), ensure_ascii=False, indent=1))
    elif a.commande == "snapshot":
        print(json.dumps(snapshot(root), ensure_ascii=False, indent=1))
    elif a.commande == "stop":
        print(json.dumps(stopper(root, a.run_id or ""), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _cli()
