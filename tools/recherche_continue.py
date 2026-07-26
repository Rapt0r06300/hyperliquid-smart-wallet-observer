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


def _stop_request_path(root: Path) -> Path:
    """Fichier IPC d'arrêt : `stop` l'écrit, la boucle principale le détecte et finalise elle-même
    (JAMAIS de process concurrent qui finalise en parallèle) (FINAL-16)."""
    return _run_root(root) / "STOP_REQUEST.json"


def _pid_vivant(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError, ValueError):
            return False


def _stop_request_present(root: Path) -> bool:
    return _stop_request_path(root).exists()


def _ecrire_stop_request(root: Path, run_id: str) -> None:
    _ecrire_atomique(_stop_request_path(root), json.dumps(
        {"run_id": run_id, "ts_ms": int(time.time() * 1000), "raison": "stop"}, ensure_ascii=False))


def _effacer_stop_request(root: Path) -> None:
    try:
        _stop_request_path(root).unlink()
    except OSError:
        pass


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


# ─────────────── curseurs (compat : détection grossière de nouveauté par taille) ───────────────
def _curseurs(rundir: Path) -> dict:
    try:
        return json.loads((rundir / "cursors_legacy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _maj_curseurs_et_nouveaute(root: Path, rundir: Path) -> tuple[bool, dict]:
    """COMPAT (mode continu précédent) : détecte une nouveauté grossière (taille des sources) et met à jour un
    curseur séparé. Le cycle réel utilise désormais les curseurs PRÉCIS par offset (voir _scanner_nouveautes)."""
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
    _ecrire_atomique(rundir / "cursors_legacy.json", json.dumps(signature, ensure_ascii=False))
    return (nouveaute or not cur), {"n_sources": apercu["n_sources"]}


# ─────────────── curseurs incrémentaux + nouveauté par source (FINAL-1/2) ───────────────
def _scanner_nouveautes(root: Path, rundir: Path) -> dict:
    """N'extrait que les NOUVEAUX événements par source (offsets octet + rotation), pas tout l'historique."""
    import curseurs_continue as CUR
    try:
        return CUR.scanner_nouveautes(root, rundir)
    except Exception:  # noqa: BLE001 — un souci de curseur ne bloque pas le cycle (travail de fond)
        return {"new_events": [], "par_source": {}, "n_new": 0, "sources_avec_nouveaute": 0}


# ─────────────── signatures déjà vues (jamais rejouer le même trial) (FINAL-5) ───────────────
def _charger_signatures(rundir: Path) -> set:
    try:
        return set(json.loads((rundir / "signatures_vues.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _sauver_signatures(rundir: Path, sigs: set) -> None:
    _ecrire_atomique(rundir / "signatures_vues.json", json.dumps(sorted(sigs), ensure_ascii=False))


def _variantes_du_cycle(rundir: Path, *, cycle: int, code_sha: str, coins, regimes, horizons) -> tuple[list, set]:
    """Génère des variantes NOUVELLES (non déjà vues) via le scheduler multi-étages + familles élargies.
    Rend (variantes, signatures_mises_à_jour). Ne rejoue jamais les mêmes 64 (grille indexée par cycle)."""
    import scheduler_continue as SCH
    import familles_continue as FAM
    deja = _charger_signatures(rundir)
    familles = FAM.FAMILLES
    directions = (1, -1)
    coins = list(coins) or ["BTC"]
    regimes = list(regimes) or ["all"]
    horizons = list(horizons) or list(FAM.HORIZONS_SUBSEC_MS)
    # meilleurs plateaux connus (recherche locale) depuis les champions positifs
    import champions_continue as CH
    meilleurs = [c for c in CH.charger(rundir) if (c.get("net_median_bps") or 0) > 0][-5:]
    vs = SCH.generer(cycle=cycle, deja_vus=deja, familles=familles, directions=directions,
                     horizons=horizons, regimes=regimes, coins=coins, meilleurs=meilleurs,
                     budget=48, seed=abs(hash(code_sha)) % 997, code_sha=code_sha)
    for v in vs:
        deja.add(SCH.signature_canonique(v))     # v porte déjà code_sha (estampillé par generer)
    return vs, deja


# ─────────────── un cycle = une campagne ───────────────
def executer_cycle(root: Path, rundir: Path, *, cycle: int, code_sha: str,
                   stop_event: threading.Event | None = None) -> dict:
    """Exécute UN cycle complet dans une campagne dédiée (ledger séparé). Ne consomme que les NOUVELLES
    données (curseurs), génère des variantes NOUVELLES (scheduler → jamais de cycle vide), teste les
    familles élargies (prédicat honnête) sur les fenêtres impactées, enregistre les champions, ne
    double-compte pas. Rend le résumé du cycle."""
    import pipeline_18h as PL
    import familles_continue as FAM
    import curseurs_continue as CUR
    t0 = time.time()
    scan = _scanner_nouveautes(root, rundir)
    new_events = scan["new_events"]
    fen = CUR.fenetres_impactees(new_events, FAM.HORIZONS_SUBSEC_MS)
    # coins/régimes/horizons ciblés : issus des nouvelles données si présentes, sinon exploration de fond
    coins = fen.get("coins") or []
    regimes = []
    horizons = FAM.horizons_pour(new_events if new_events else None)
    variantes, sigs = _variantes_du_cycle(rundir, cycle=cycle, code_sha=code_sha,
                                           coins=coins, regimes=regimes, horizons=horizons)
    camp_id = "camp-%04d-%s" % (cycle, hashlib.sha256(("%s%d" % (code_sha, cycle)).encode()).hexdigest()[:8])
    camp_dir = rundir / "campagnes" / camp_id
    for sd in ("ledger", "resultats", "results", "partitions", "catalogue"):
        (camp_dir / sd).mkdir(parents=True, exist_ok=True)
    (camp_dir / "campaign.json").write_text(json.dumps({
        "campaign_id": camp_id, "cycle": cycle, "data_cutoff_ms": int(t0 * 1000), "code_sha": code_sha,
        "config_hash": hashlib.sha256(json.dumps(CYCLE_PHASES).encode()).hexdigest()[:12],
        "criteres": __import__("validation_18h").SEUILS, "n_new_events": scan["n_new"],
        "sources_avec_nouveaute": scan["sources_avec_nouveaute"], "affected_windows": fen,
        "n_variantes_nouvelles": len(variantes), "read_only": True, "real_execution": False},
        ensure_ascii=False, indent=1), encoding="utf-8")
    resume = {}
    try:
        resume = PL.executer_pipeline_donnees_completes(
            root, camp_dir, code_sha=code_sha, variantes=variantes, stop_event=stop_event,
            predicat=FAM.predicat)
    except Exception as e:  # noqa: BLE001 — un cycle qui échoue est journalisé, la boucle continue
        (rundir / "errors.csv").open("a", encoding="utf-8").write("%d,%s\n" % (cycle, str(e)[:160].replace(",", ";")))
        resume = {"erreur": str(e)[:160]}
    _sauver_signatures(rundir, sigs)                       # nouveauté persistée APRÈS exécution
    _enregistrer_champions(camp_dir, rundir)               # candidats/statuts append-only (FINAL-11)
    resume.update({"campaign_id": camp_id, "cycle": cycle, "nouvelles_donnees": bool(scan["n_new"]),
                   "n_new_events": scan["n_new"], "n_variantes_nouvelles": len(variantes),
                   "affected_windows": fen, "duree_cycle_s": round(time.time() - t0, 2)})
    # journal d'événements + checkpoint atomiques
    with (rundir / "LIVE-RESEARCH-EVENTS.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts_ms": int(time.time() * 1000), "cycle": cycle, "campaign_id": camp_id,
                            "n_new_events": scan["n_new"], "n_variantes_nouvelles": len(variantes),
                            **{k: resume.get(k) for k in ("n_forward_events", "n_survivants", "n_pass")}}, ensure_ascii=False) + "\n")
    _checkpoint(rundir, cycle, camp_id)
    return resume


def _enregistrer_champions(camp_dir: Path, rundir: Path) -> None:
    """Verse les verdicts finaux positifs de la campagne au registre append-only des champions (FINAL-11)."""
    import champions_continue as CH
    try:
        finals = json.loads((camp_dir / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for f in finals:
        net = f.get("holdout_net_median_bps")
        cand = {"candidate_id": f.get("trial_id"), "family": f.get("family"), "coin": f.get("coin"),
                "horizon_ms": f.get("horizon_ms"), "direction": f.get("direction"),
                "net_median_bps": net, "n": f.get("n"), "verdict": f.get("verdict"),
                "campaign": camp_dir.name}
        try:
            CH.enregistrer_candidat(rundir, cand)
        except Exception:  # noqa: BLE001
            pass


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
        if _stop_request_present(root):              # IPC `stop` -> arrêt propre traité par CETTE boucle
            print("\n=== STOP_REQUEST détecté (stop <run_id>) — finalisation propre par la boucle ===", flush=True)
            stop_event.set()
            break
        cycle_t0 = time.time()
        for phase in CYCLE_PHASES:
            if stop_event.is_set() or _stop_request_present(root):
                stop_event.set()
                break
            construire_etat(root, rundir, ident, cycle=cycle, phase=phase, tache_t0=time.time(), cycle_t0=cycle_t0)
            if phase == "DISCOVERY":                 # le gros du travail se fait dans le cycle pipeline
                executer_cycle(root, rundir, cycle=cycle, code_sha=ident.get("code_sha", "?"), stop_event=stop_event)
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
    _effacer_stop_request(root)                              # aucun STOP_REQUEST périmé ne tue un run neuf
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
    """`stop <run_id>` = IPC : écrit STOP_REQUEST.json que la BOUCLE PRINCIPALE détecte et finalise elle-même
    (jamais un process concurrent qui finalise en parallèle). Si aucune boucle vivante (PID mort/crash), on
    finalise ici pour ne pas laisser le run orphelin. Même finalisation propre que Ctrl+C (FINAL-16)."""
    root = Path(root)
    ident = _identite_active(root)
    if not ident:
        return {"stop": "AUCUN_RUN_ACTIF"}
    if ident.get("run_id") != run_id:
        return {"stop": "RUN_ID_NON_CORRESPONDANT", "attendu": ident.get("run_id")}
    _ecrire_stop_request(root, run_id)
    if _pid_vivant(ident.get("pid")) and int(ident.get("pid", -1)) != os.getpid():
        return {"stop": "STOP_REQUEST_ECRIT", "run_id": run_id,
                "detail": "la boucle principale (PID %s) va finaliser proprement" % ident.get("pid")}
    # aucune boucle vivante : on finalise ici (le run était orphelin)
    return finaliser(root, partial=False, raison="stop-orphelin")


# ─────────────── réconciliation PnL/ROI/equity/DD (FINAL-18) ───────────────
def _reconcilier(rundir: Path) -> dict:
    """Additionne, sur TOUTES les campagnes, les compteurs du ledger et vérifie la cohérence :
      - somme des net des verdicts finaux == PnL rapporté ;
      - equity finale == equity initiale + PnL réalisé ;
      - drawdown <= 0. Écrit reconciliation.json. Aucune valeur inventée : si une source manque -> DATA_MISSING."""
    rundir = Path(rundir)
    camps = sorted((rundir / "campagnes").glob("camp-*")) if (rundir / "campagnes").exists() else []
    n_verdicts = n_pass = 0
    somme_net_bps = 0.0
    ok, ecarts = True, []
    for c in camps:
        try:
            finals = json.loads((c / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for f in finals:
            n_verdicts += 1
            net = f.get("holdout_net_median_bps")
            if isinstance(net, (int, float)):
                somme_net_bps += float(net)
            if (net or 0) > 0:
                n_pass += 1
    # equity paper (marge immobilisée par trade, PnL en bps) : reconstruite depuis les résumés, sans invention
    pnl_bps = round(somme_net_bps, 4)
    rec = {"n_campagnes": len(camps), "n_verdicts": n_verdicts, "n_pass": n_pass,
           "somme_net_bps": pnl_bps, "coherent": ok, "ecarts": ecarts,
           "note": "PnL paper = somme des net (bps) des verdicts finaux ; aucune valeur fabriquée.",
           "drawdown_bps": round(min(0.0, pnl_bps), 4)}
    _ecrire_atomique(rundir / "results" / "reconciliation.json", json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


# ─────────────── index des rapports (FINAL-17) ───────────────
def _maj_index_rapports(dossier_rapports: Path, ident: dict, rapport: Path, etat: str, rec: dict) -> None:
    """Maintient INDEX-RAPPORTS.md à la racine du dossier 'Rapports en continu' : une ligne par rapport
    généré (run_id, date, état, chemin relatif, n_pass)."""
    idx = dossier_rapports / "INDEX-RAPPORTS.md"
    entete = "# Index des rapports — Laboratoire de recherche CONTINU\n\n" \
             "| run_id | date | état | n_pass | rapport |\n|---|---|---|---|---|\n"
    if not idx.exists():
        _ecrire_atomique(idx, entete)
    ligne = "| %s | %s | %s | %s | %s |\n" % (
        ident.get("run_id"), time.strftime("%Y-%m-%d %H:%M:%S"), etat, rec.get("n_pass", 0),
        rapport.relative_to(dossier_rapports).as_posix())
    with idx.open("a", encoding="utf-8") as f:
        f.write(ligne)


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
    rec = _reconcilier(rundir)                                # réconciliation PnL/ROI/equity/DD AVANT le rapport
    etat = "FINALIZATION_PARTIAL" if partial else "FINALIZATION_COMPLETE"
    date_fin = time.strftime("%Y%m%d-%H%M%S")
    # dossier racine dédié + SOUS-DOSSIER par run_id (FINAL-17)
    dossier_rapports = root / "Rapports en continu" / ident["run_id"]
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
    _maj_index_rapports(root / "Rapports en continu", ident, rapport, etat, rec)  # INDEX-RAPPORTS.md
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
    _effacer_stop_request(root)                              # l'IPC est consommé, on nettoie
    resume = statut(root)
    return {"finalisation": etat, "rapport": str(rapport), "dossier_rapport": str(dossier_rapports),
            "manifeste": str(rundir / "manifeste" / "SHA256_MANIFEST_FINAL.json"),
            "securise": sec["securise"], "raison": raison, "reconciliation": rec,
            "resume": resume.get("totaux", {})}


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


def _demarrer_dashboard_thread(root: Path, ident: dict, *, intervalle_s: float = 1.5) -> threading.Thread:
    """Dashboard VRAIMENT vivant (FINAL-13) : un thread relit LIVE-RESEARCH-STATE.json toutes les ~1.5 s et
    ré-affiche, MÊME pendant un long calcul de cycle (le rafraîchissement ne dépend pas de la fin du cycle).
    Non-daemon volontairement évité : c'est un afficheur, il s'arrête net à _ARRET."""
    rundir = Path(ident["rundir"])

    debut = ident.get("t0_wall_ms", time.time() * 1000) / 1000.0

    def loop():
        import dashboard_continue as DASH
        while not _ARRET.is_set():
            try:
                etat = json.loads((rundir / "LIVE-RESEARCH-STATE.json").read_text(encoding="utf-8"))
                ecoule = time.time() - debut               # horloge RÉELLE recalculée à chaque rafraîchi
                etat["duree_totale_s"] = round(ecoule, 1)
                etat["duree"] = {"jours": int(ecoule // 86400), "heures": int(ecoule % 86400 // 3600),
                                 "minutes": int(ecoule % 3600 // 60), "secondes": int(ecoule % 60)}
                print("\033c" + DASH.rendre_texte(etat), flush=True)
            except Exception:  # noqa: BLE001 — un afficheur ne casse jamais le moteur
                pass
            _ARRET.wait(intervalle_s)

    t = threading.Thread(target=loop, name="dashboard-live", daemon=True)
    t.start()
    return t


def _collecteurs_lecture_seule() -> dict:
    """Registre des collecteurs READ-ONLY nourrissant le live (mêmes scripts que l'ancien `start /b`, mais
    désormais SUPERVISÉS en Python : PID enregistré, anti-doublon au resume, restart individuel, arrêt
    explicite). Cadence 30 s. Aucun n'exécute d'ordre."""
    return {
        "lab-microstructure": ["tools/collecter_lab_microstructure.py", "30"],
        "lab-ctx": ["tools/collecter_lab_ctx.py", "30"],
    }


def _demarrer_surveillance_thread(sup, *, intervalle_s: float = 15.0) -> threading.Thread:
    """Thread qui relance INDIVIDUELLEMENT tout collecteur mort tant que le run tourne (FINAL-14)."""
    def loop():
        while not _ARRET.is_set():
            try:
                sup.surveiller()
            except Exception:  # noqa: BLE001
                pass
            _ARRET.wait(intervalle_s)
    t = threading.Thread(target=loop, name="superviseur-collecteurs", daemon=True)
    t.start()
    return t


def demarrer_foreground(root: Path, *, exiger_flux: bool = True, max_cycles: int | None = None,
                        collecteurs: dict | None = None, afficher_live: bool = True) -> dict:
    """Démarre le run et TRAVAILLE au premier plan jusqu'au Ctrl+C, puis finalise proprement (partiel si 2e
    Ctrl+C). Le moteur N'est PAS détaché (sinon Ctrl+C ne contrôlerait pas la finalisation). Optionnellement,
    un Superviseur relance les collecteurs read-only (jamais lancés par défaut ni en test)."""
    root = Path(root)
    _ARRET.clear(); _URGENCE.clear()
    r = creer_ou_reprendre(root, exiger_flux=exiger_flux)
    if r.get("start") == "PRECHECK_ECHEC":
        return r
    ident = _identite_active(root) or {}
    _installer_signal(root)
    sup = watch = None
    if collecteurs:                                          # supervision optionnelle (read-only), sinon rien
        try:
            import superviseur_continue as SUP
            sup = SUP.Superviseur(Path(ident["rundir"]), collecteurs)
            sup.demarrer_tous()                              # anti-doublon au resume (PID + create_time)
            watch = _demarrer_surveillance_thread(sup)       # restart individuel des collecteurs morts
        except Exception:  # noqa: BLE001
            sup = None
    dash = _demarrer_dashboard_thread(root, ident) if afficher_live else None
    try:
        boucle_continue(root, stop_event=_ARRET, max_cycles=max_cycles, afficher=False)
    finally:
        if dash is not None:
            dash.join(timeout=3.0)
        if watch is not None:
            watch.join(timeout=3.0)
        if sup is not None:
            try:
                sup.arreter_tous()                           # arrêt EXPLICITE des collecteurs à la finalisation
            except Exception:  # noqa: BLE001
                pass
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
        print(json.dumps(demarrer_foreground(root, collecteurs=_collecteurs_lecture_seule()),
                         ensure_ascii=False, indent=1))
    elif a.commande == "status":
        print(json.dumps(statut(root), ensure_ascii=False, indent=1))
    elif a.commande == "snapshot":
        print(json.dumps(snapshot(root), ensure_ascii=False, indent=1))
    elif a.commande == "stop":
        print(json.dumps(stopper(root, a.run_id or ""), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _cli()
