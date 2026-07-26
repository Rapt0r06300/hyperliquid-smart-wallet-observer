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
    # NE PAS persister ici : une signature n'est « définitivement vue » qu'après résultat TERMINAL (PT-7).
    return vs, deja


def _maturer_live(rundir: Path, new_events: list) -> tuple[list, dict]:
    """AF-P1 : ingère les nouveaux événements dans le CanonicalStore (PENDING), les mûrit contre un buffer de
    marché persistant (les ticks FUTURS arrivés aux cycles suivants), puis consomme les épisodes READY
    (FWD_BOOK, promouvables). Les PENDING survivent aux cycles/redémarrages. Rend (episodes_prets, compte)."""
    try:
        import canonical_store as CS
    except Exception:  # noqa: BLE001
        return [], {"canonical": "INDISPONIBLE"}
    rundir = Path(rundir)
    buf = rundir / "canonical" / "marche.jsonl"
    buf.parent.mkdir(parents=True, exist_ok=True)
    with buf.open("a", encoding="utf-8") as f:               # buffer marché append-only (ticks futurs)
        for e in new_events:
            c = str(e.get("coin") or e.get("symbol") or "").upper()
            ts = e.get("exchange_ts") or e.get("ts_ms") or e.get("ts_wall_ms")   # FX-8 : exchange_ts prioritaire (même horloge que l'ingestion)
            if c and ts is not None and e.get("bid") is not None and e.get("ask") is not None:
                tick = {"coin": c, "ts_ms": float(ts), "bid": float(e["bid"]), "ask": float(e["ask"])}
                if e.get("bids") is not None and e.get("asks") is not None:       # vrai L2 futur si présent (FX-8)
                    tick["bids"], tick["asks"] = e["bids"], e["asks"]
                f.write(json.dumps(tick) + "\n")
    # relit un buffer BORNÉ (les N derniers ticks par coin) pour la maturation
    marche: dict = {}
    for l in buf.read_text(encoding="utf-8", errors="ignore").splitlines()[-20000:]:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        marche.setdefault(d["coin"], []).append(d)
    store = CS.CanonicalStore(rundir)
    store.ingerer(new_events)
    maintenant = max((t["ts_ms"] for ticks in marche.values() for t in ticks), default=0.0)
    mat = store.maturer(marche, maintenant_ms=maintenant)
    prets = store.consommer()
    _ecrire_atomique(rundir / "canonical" / "maturation.json",
                     json.dumps({**mat, "consommes": len(prets), "compte": store.compte()}, ensure_ascii=False, indent=1))
    return prets, {"muris": mat.get("maries"), "consommes": len(prets), "backlog": mat.get("backlog"), "compte": store.compte()}


def _securite_run(root: Path, rundir: Path) -> bool:
    """Audit sécurité fait UNE FOIS par run (mis en cache) — évite un scan complet du dépôt à chaque campagne.
    Sert de `securite_verte` au gate (UF-3/§8 : audit AVANT le gate final)."""
    cache = Path(rundir) / "security_ok.json"
    try:
        return bool(json.loads(cache.read_text(encoding="utf-8"))["securise"])
    except (OSError, ValueError, KeyError):
        pass
    try:
        ok = bool(SEC.auditer(root)["securise"])
    except Exception:  # noqa: BLE001
        ok = None
    _ecrire_atomique(cache, json.dumps({"securise": ok, "ts_ms": int(time.time() * 1000)}, ensure_ascii=False))
    return ok


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
    try:
        import progres_live as PROG                          # FX-2 : progression fine PENDANT le calcul
        PROG.reset(7, job="lecture des nouvelles données", ensuite="maturation live")
    except Exception:  # noqa: BLE001
        PROG = None
    def _prog(n, job, ensuite=None):
        if PROG is not None:
            try:
                PROG.publier(n, 7, job=job, ensuite=ensuite)
            except Exception:  # noqa: BLE001
                pass
    t0 = time.time()
    scan = _scanner_nouveautes(root, rundir)
    new_events = scan["new_events"]
    fen = CUR.fenetres_impactees(new_events, FAM.HORIZONS_SUBSEC_MS)
    # coins/régimes/horizons ciblés : issus des nouvelles données si présentes, sinon exploration de fond
    coins = fen.get("coins") or []
    regimes = []
    horizons = FAM.horizons_pour(new_events if new_events else None)
    variantes, deja = _variantes_du_cycle(rundir, cycle=cycle, code_sha=code_sha,
                                          coins=coins, regimes=regimes, horizons=horizons)
    # 7 files prioritaires RÉELLEMENT enfilées + consommées (PT-7) ; l'exploration porte les variantes
    import scheduler_continue as SCH
    import champions_continue as CH
    plan = SCH.planifier_cycle(
        sante_ingestion=(1 + scan["sources_avec_nouveaute"]), forward_figes=len(CH.charger(rundir)),
        exact_survivants=0, validation_stress=0, exploration=variantes,
        amelioration_locale=len([c for c in CH.charger(rundir) if (c.get("net_median_bps") or 0) > 0]),
        analyse_rejets=1)
    camp_id = "camp-%04d-%s" % (cycle, hashlib.sha256(("%s%d" % (code_sha, cycle)).encode()).hexdigest()[:8])
    camp_dir = rundir / "campagnes" / camp_id
    for sd in ("ledger", "resultats", "results", "partitions", "catalogue"):
        (camp_dir / sd).mkdir(parents=True, exist_ok=True)
    (camp_dir / "scheduler_state.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (camp_dir / "campaign.json").write_text(json.dumps({
        "campaign_id": camp_id, "cycle": cycle, "data_cutoff_ms": int(t0 * 1000), "code_sha": code_sha,
        "config_hash": hashlib.sha256(json.dumps(CYCLE_PHASES).encode()).hexdigest()[:12],
        "criteres": __import__("validation_18h").SEUILS, "n_new_events": scan["n_new"],
        "sources_avec_nouveaute": scan["sources_avec_nouveaute"], "affected_windows": fen,
        "n_variantes_nouvelles": len(variantes), "files_consommees": plan["files_consommees"],
        "read_only": True, "real_execution": False}, ensure_ascii=False, indent=1), encoding="utf-8")
    _prog(1, "maturation des données live", "rejeu exact des idées")
    prets, mat = _maturer_live(rundir, new_events)             # AF-P1 : maturation live -> épisodes FWD_BOOK
    resume = {}
    interrompu = bool(stop_event is not None and stop_event.is_set())
    _prog(2, "rejeu exact + validation (le gros du calcul)", "portefeuille + jobs de fond")
    try:
        resume = PL.executer_pipeline_donnees_completes(
            root, camp_dir, code_sha=code_sha, variantes=variantes, stop_event=stop_event,
            predicat=FAM.predicat, new_events=new_events, affected_windows=fen, hist_dir=rundir,
            securise=_securite_run(root, rundir), episodes_prets=prets,
            portefeuille_global_dir=(rundir / "global_portfolio"))   # AF-P3 : UN portefeuille pour tout le run
    except Exception as e:  # noqa: BLE001 — un cycle qui échoue est journalisé, la boucle continue
        (rundir / "errors.csv").open("a", encoding="utf-8").write("%d,%s\n" % (cycle, str(e)[:160].replace(",", ";")))
        resume = {"erreur": str(e)[:160]}
    interrompu = interrompu or bool(stop_event is not None and stop_event.is_set())
    # PT-7 : ne persiste comme « vues » que les variantes ayant atteint un résultat TERMINAL (préregistrées).
    # Une variante interrompue reste RETRYABLE (non persistée -> régénérée au prochain cycle).
    n_term = int(resume.get("n_preregistres", 0 if interrompu else len(variantes)))
    _sauver_signatures(rundir, SCH.marquer_vues(deja, variantes, n_term))
    _prog(3, "enregistrement des champions", "jobs de fond")
    _enregistrer_champions(camp_dir, rundir)               # candidats/statuts append-only (FINAL-11)
    _prog(4, "jobs de fond (stress/placebo/WF/LOCO/LORO)", "outils d'optimisation")
    jobs_resume = _travail_de_fond(rundir, camp_dir)       # AF-P4 : jobs réellement exécutés (aucun idle)
    _prog(5, "outils d'optimisation (grid/random/QMC/Optuna)", "suivi live des candidats")
    _outils_recherche(rundir, camp_dir)                    # AF-P5 : registre d'outils réellement lancés
    _prog(6, "suivi live des candidats figés", "clôture du cycle")
    suivi = _suivi_candidats_live(rundir, prets)           # FX-5 : suivi live run-level (épisodes après freeze)
    _promouvoir_pass_live(rundir, camp_dir)                # POINT 2 : PASS_FORWARD_PAPER SEULEMENT si prouvé live
    _prog(7, "clôture du cycle", "nouveau cycle")
    resume.update({"campaign_id": camp_id, "cycle": cycle, "nouvelles_donnees": bool(scan["n_new"]),
                   "n_new_events": scan["n_new"], "n_variantes_nouvelles": len(variantes),
                   "affected_windows": fen, "maturation": mat,
                   "jobs": {k: jobs_resume.get(k) for k in ("n_jobs_executes", "n_done", "aucun_idle")},
                   "candidats_live": suivi, "duree_cycle_s": round(time.time() - t0, 2)})
    # journal d'événements + checkpoint atomiques
    with (rundir / "LIVE-RESEARCH-EVENTS.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts_ms": int(time.time() * 1000), "cycle": cycle, "campaign_id": camp_id,
                            "n_new_events": scan["n_new"], "n_variantes_nouvelles": len(variantes),
                            **{k: resume.get(k) for k in ("n_forward_events", "n_survivants", "n_pass")}}, ensure_ascii=False) + "\n")
    _checkpoint(rundir, cycle, camp_id)
    return resume


def _corpus_reel_du_run(rundir: Path):
    """Corpus RÉEL du run (FX-3) : épisodes historiques (historique/episodes.jsonl) + épisodes live MÛRIS et
    consommés (canonical/ready.jsonl, FWD_BOOK). Fixtures SEULEMENT en dernier repli, et alors marqué SYNTHÉTIQUE
    pour que ses résultats n'entrent JAMAIS dans les compteurs réels du dashboard. Rend (corpus, source)."""
    import pipeline_18h as PL
    rundir = Path(rundir)
    corp = []
    hist = rundir / "historique" / "episodes.jsonl"
    if hist.exists():
        with hist.open("r", encoding="utf-8", errors="ignore") as f:
            for i, l in enumerate(f):
                if i >= 5000:
                    break
                try:
                    corp.append(json.loads(l))
                except ValueError:
                    continue
    ready = rundir / "canonical" / "ready.jsonl"                # épisodes live mûris (FWD_BOOK)
    if ready.exists():
        lignes = ready.read_text(encoding="utf-8", errors="ignore").splitlines()[-5000:]
        for l in lignes:
            try:
                corp.append(json.loads(l))
            except ValueError:
                continue
    if corp:
        return corp, "REEL_RUN"
    return PL.corpus_fixtures(), "SYNTHETIC_FALLBACK"


def _travail_de_fond(rundir: Path, camp_dir: Path) -> dict:
    """AF-P4 : à chaque cycle, exécute RÉELLEMENT des jobs utiles (stress/placebo/WF/LOCO/LORO/voisins/
    revalidation/analyse rejets) sur le corpus RÉEL du run et les champions. Jamais d'idle. Défensif."""
    try:
        import jobs_continue as JOBS
        import pipeline_18h as PL
        import familles_continue as FAM
        import champions_continue as CH
        corp, _corp_source = _corpus_reel_du_run(rundir)       # FX-3 : corpus réel (historique + live mûri)
        def _ev_seuil(cand, seuil):
            sub = PL._filtrer_corpus(corp, predicat=FAM.predicat, family=cand.get("family", "GENERIC"), seuil=seuil)
            return PL._nets_promo(PL.nets_exact(sub, sens=cand["direction"], horizon_ms=cand["horizon_ms"]))
        def _ev_famille(sub_corpus, cand):
            """MÊME famille + prédicat + seuil + direction + horizon du candidat, sur un sous-corpus (LOCO/LORO)."""
            ss = PL._filtrer_corpus(sub_corpus, predicat=FAM.predicat, family=cand.get("family", "GENERIC"),
                                    seuil=cand.get("seuil", 8))
            return PL._nets_promo(PL.nets_exact(ss, sens=cand["direction"], horizon_ms=cand["horizon_ms"]))
        ctx = {"corpus": corp,
               "evaluer_promo": lambda c, s, h: PL._nets_promo(PL.nets_exact(c, sens=s, horizon_ms=h)),
               "evaluer_objets": lambda c, s, h: PL.nets_exact(c, sens=s, horizon_ms=h),  # objets par épisode (WF sans zip)
               "evaluer_seuil": _ev_seuil, "evaluer_famille": _ev_famille}
        champs = [c for c in CH.charger(rundir) if c.get("direction") and c.get("horizon_ms")][-5:]
        cands = [{"family": c.get("family", "GENERIC"), "direction": c["direction"], "horizon_ms": c["horizon_ms"],
                  "seuil": 8} for c in champs] or [{"family": "GENERIC", "direction": 1, "horizon_ms": 1000, "seuil": 8}]
        rejets = []
        try:
            rejets = [f for f in json.loads((camp_dir / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))
                      if f.get("verdict") in ("KILL", "DATA_MISSING", "SHADOW")]
        except (OSError, ValueError):
            pass
        return JOBS.travail_de_fond(rundir, ctx, candidats=cands, rejets=rejets)
    except Exception as e:  # noqa: BLE001
        return {"erreur": str(e)[:160]}


def _outils_recherche(rundir: Path, camp_dir: Path) -> dict:
    """AF-P5 : lance les outils d'optimisation DISPONIBLES sur un vrai objectif multi-critères (score composite
    d'une évaluation promouvable), écrit leur tableau d'état. Défensif."""
    try:
        import outils_recherche as OUT
        import pipeline_18h as PL
        import statistics
        corp, corp_source = _corpus_reel_du_run(rundir)        # FX-3 : corpus RÉEL du run, plus de fixtures en prod
        def _eval(params, budget: float = 1.0):
            # GR-4 : `budget` in (0,1] = part CROISSANTE des données (Hyperband/Successive Halving alloue plus
            # d'événements à chaque étape). On coupe le corpus au prorata (au moins 8 épisodes pour rester mesurable).
            sens = 1 if params.get("direction", 1) >= 0 else -1
            h = int(params.get("horizon_ms", 1000))
            n_budget = max(8, int(len(corp) * max(0.0, min(1.0, float(budget)))))
            sous = corp[:n_budget]
            nets = PL._nets_promo(PL.nets_exact(sous, sens=sens, horizon_ms=h))
            nm = statistics.median(nets) if nets else -50.0
            pf = PL._profit_factor(nets) if nets else 0.0
            return {"net_median_bps": nm, "pf": (pf if isinstance(pf, (int, float)) else 1.0), "n": len(nets)}
        espace = {"direction": [1, -1], "horizon_ms": [250, 1000, 5000]}
        reg = OUT.lancer_registre(_eval, espace, n_trials=8, storage_dir=(rundir / "optuna"))
        reg["disponibilite"] = OUT.disponibilite()
        reg["corpus_source"] = corp_source
        reg["synthetique"] = (corp_source != "REEL_RUN")        # FX-3 : jamais compté comme réel si synthétique
        _ecrire_atomique(camp_dir / "resultats" / "outils_recherche.json", json.dumps(reg, ensure_ascii=False, indent=1))
        return reg
    except Exception as e:  # noqa: BLE001
        return {"erreur": str(e)[:160]}


def _horloge_live(rundir: Path, prets_live: list):
    """Dernier exchange_ts RÉELLEMENT observé (point 1) : max des ts des épisodes live consommés, sinon dernier
    tick du buffer marché du CanonicalStore (canonical/marche.jsonl). Rend None si AUCUNE horloge live valide
    (> 0) — dans ce cas on NE GÈLE PAS (WAITING_FOR_LIVE_CLOCK)."""
    m = 0.0
    for e in (prets_live or []):
        try:
            m = max(m, float(e.get("ts_ms") or 0.0))
        except (TypeError, ValueError):
            continue
    if m <= 0.0:
        buf = Path(rundir) / "canonical" / "marche.jsonl"
        if buf.exists():
            try:
                with buf.open("r", encoding="utf-8", errors="ignore") as f:
                    lignes = f.readlines()[-500:]
                for l in reversed(lignes):
                    l = l.strip()
                    if not l:
                        continue
                    try:
                        t = float(json.loads(l).get("ts_ms") or 0.0)
                    except (ValueError, TypeError):
                        continue
                    if t > m:
                        m = t
                        break
            except OSError:
                pass
    return m if m > 0.0 else None


def _suivi_candidats_live(rundir: Path, prets_live: list) -> dict:
    """FX-5 + GR-1/GR-2 : registre RUN-LEVEL des candidats figés, suivi CUMULATIF et alimentation du portefeuille
    GLOBAL depuis le SEUL vrai live. Fige les champions (freeze immuable), puis, pour chaque candidat (y compris
    des cycles précédents), ne prend que les NOUVEAUX épisodes live FWD_BOOK arrivés APRÈS son freeze_exchange_ts
    (dédup par episode_id) : (1) cumule PnL/ROI/DD/n_episodes ; (2) OUVRE/FERME dans le portefeuille GLOBAL. Le
    pré-forward historique (archive) n'alimente JAMAIS ce portefeuille. Un cycle vide ne remet rien à zéro."""
    try:
        import registre_candidats_live as RCL
        import champions_continue as CH
        import pipeline_18h as PL
        import portefeuille_global as PG
        import forward_portefeuille as FPF
        import moteur_execution_prod as MEP
        reg = RCL.RegistreCandidatsLive(rundir)
        maintenant = _horloge_live(rundir, prets_live)        # point 1 : dernier exchange_ts RÉELLEMENT observé (jamais 0)
        # 1) figer les champions courants au dernier exchange_ts live. Sans horloge live valide (maintenant None),
        #    figer() bascule le candidat en WAITING_FOR_LIVE_CLOCK et NE GÈLE PAS (freeze=0 interdit).
        for c in CH.charger(rundir):
            cid = c.get("trial_id") or c.get("candidate_id")
            if cid and c.get("direction") and c.get("horizon_ms"):
                reg.figer(cid, freeze_exchange_ts=maintenant,
                          meta={"direction": c["direction"], "horizon_ms": c["horizon_ms"],
                                "coin": c.get("coin"), "family": c.get("family")})
        if maintenant is None:                                # aucune horloge live -> rien à suivre ce cycle
            return reg.resume()
        gp_dir = rundir / "global_portfolio"                 # le SEUL portefeuille global du run (alimenté LIVE only)
        pfg = PG.PortefeuilleGlobal(gp_dir)
        gp_pending = gp_dir / "pending_exits.json"
        _ev = lambda ep, sens, horizon_ms: MEP.evaluer_episode(ep, sens=sens, horizon_ms=horizon_ms)
        _passe = lambda corp, coin=None, regime=None: corp
        # 2) suivre + alimenter le global sur les NOUVEAUX épisodes admissibles (strictement après le gel)
        for c in reg.candidats():
            cid = c["candidate_id"]; meta = c.get("meta") or {}
            coin = meta.get("coin"); direction = meta.get("direction") or 1; h = meta.get("horizon_ms") or 1000
            adm = reg.episodes_admissibles(cid, prets_live)   # STRICTEMENT après SON freeze
            sous = [e for e in adm if (not coin or e.get("coin") == coin)]
            vus_before = set(c.get("vus") or [])
            nouveaux = [e for e in sous if (e.get("episode_id") or e.get("event_id")) not in vus_before]
            # nets PAR ÉPISODE (objets, même longueur que `nouveaux` -> index sûr, jamais un zip corpus/filtré)
            objs = PL.nets_exact(nouveaux, sens=direction, horizon_ms=h) if nouveaux else []
            paires = [((nouveaux[i].get("episode_id") or nouveaux[i].get("event_id")), o.get("net_bps"))
                      for i, o in enumerate(objs)
                      if o.get("status") == "OK" and o.get("promotable") and o.get("exit_source") == "FWD_BOOK"]
            dernier = paires[-1][0] if paires else None
            reg.suivre(cid, paires=paires, last_event_id=dernier, maintenant_ms=maintenant)   # CUMULATIF + dédup
            if nouveaux:                                      # GR-2 : global alimenté par le LIVE FWD_BOOK uniquement
                cand_meta = {"trial_id": cid, "coin": coin, "regime": None, "direction": direction, "horizon_ms": h}
                FPF.simuler([cand_meta], nouveaux, filtrer=_passe, evaluer=_ev, portefeuille=pfg,
                            pending_path=gp_pending, maintenant_ms=maintenant)
        return reg.resume()
    except Exception as e:  # noqa: BLE001
        return {"erreur": str(e)[:160]}


MIN_LIVE_EPISODES_POUR_PASS = 30                             # minimum RÉEL d'épisodes post-freeze pour un PASS live


def _promouvoir_pass_live(rundir: Path, camp_dir: Path) -> dict:
    """POINT 2 : un PASS_FORWARD_PAPER n'est délivré QUE s'il est prouvé en LIVE — jamais par le pré-forward
    archive. Promeut PASS_PRE_FORWARD -> PASS_FORWARD_PAPER pour un candidat SEULEMENT si, dans RegistreCandidatsLive :
    (a) >= MIN_LIVE_EPISODES_POUR_PASS épisodes live post-freeze ; (b) PnL/ROI live calculés par le registre ;
    (c) portefeuille GLOBAL live réconcilié cohérent avec au moins un événement ; (d) AUCUNE donnée historique
    (garanti : le registre ne compte que des épisodes strictement après le freeze). Défensif."""
    try:
        import registre_candidats_live as RCL
        import portefeuille_global as PG
        reg = RCL.RegistreCandidatsLive(rundir)
        gp = Path(rundir) / "global_portfolio"
        global_ok = False
        if (gp / "ledger.jsonl").exists():
            rc = PG.PortefeuilleGlobal(gp).reconcilier()
            global_ok = bool(rc.get("coherent")) and sum((rc.get("evenements") or {}).values()) > 0
        fpath = Path(camp_dir) / "resultats" / "final_verdicts.json"
        finals = json.loads(fpath.read_text(encoding="utf-8"))
        change = False
        for f in finals:
            if f.get("verdict") != "PASS_PRE_FORWARD":
                continue
            c = reg.etat.get(f.get("trial_id"))
            live_ok = bool(c and int(c.get("n_episodes_live", 0)) >= MIN_LIVE_EPISODES_POUR_PASS
                           and c.get("pnl_live_bps") is not None and global_ok)
            if live_ok:
                f["verdict"] = "PASS_FORWARD_PAPER"
                f["live_confirme"] = True
                f["n_episodes_live"] = c["n_episodes_live"]
                f["pnl_live_bps"] = c["pnl_live_bps"]; f["roi_live_pct"] = c["roi_live_pct"]
                f["dd_live_bps"] = c["dd_live_bps"]
                f.setdefault("raisons", []).append("LIVE_CONFIRMED")
                change = True
        if change:
            _ecrire_atomique(fpath, json.dumps(finals, ensure_ascii=False, indent=1))
        return {"n_pass_live": sum(1 for f in finals if f.get("verdict") == "PASS_FORWARD_PAPER"),
                "n_pass_pre_forward": sum(1 for f in finals if f.get("verdict") == "PASS_PRE_FORWARD"),
                "global_reconcilie": global_ok}
    except Exception as e:  # noqa: BLE001
        return {"erreur": str(e)[:160]}


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
    _enrichir_etat_dashboard(root, rundir, etat, cycle=cycle, phase=phase, tot=tot, interessantes=interessantes)
    _ecrire_atomique(rundir / "LIVE-RESEARCH-STATE.json", json.dumps(etat, ensure_ascii=False, indent=1))
    try:
        import dashboard_continue as DASH
        _ecrire_atomique(rundir / "LIVE-RESEARCH-DASHBOARD.md", DASH.rendre_markdown(etat))
    except Exception:  # noqa: BLE001
        pass
    return etat


_PHRASES_PHASE = {
    "INGESTION": ("je range les nouvelles données du marché", "il faut des prix propres pour tester"),
    "DISCOVERY": ("je cherche de nouvelles idées de trade", "trouver un signal qui devance le prix"),
    "FAST_SCREEN": ("je fais un test rapide des idées", "écarter vite les mauvaises pistes"),
    "EXACT_REPLAY": ("je rejoue une idée au prix exécutable", "vérifier qu'elle gagne APRÈS les coûts"),
    "VALIDATION": ("je teste la solidité d'une piste", "être sûr que ce n'est pas de la chance"),
    "HOLDOUT": ("je teste sur des données jamais vues", "éviter de me mentir à moi-même"),
    "FORWARD_PAPER": ("je suis une piste sur les données récentes", "voir si elle tient en conditions réelles"),
    "ANALYSE": ("je résume ce que j'ai appris", "garder seulement ce qui survit"),
}


def _enrichir_etat_dashboard(root, rundir, etat, *, cycle, phase, tot, interessantes) -> None:
    """AF-P6 : ajoute à l'état les champs des 12 panneaux (mots simples). Valeurs absentes = laissées None
    -> le dashboard affiche « PAS ENCORE CALCULABLE »."""
    rundir = Path(rundir)
    phrase, pourquoi = _PHRASES_PHASE.get(phase, ("je travaille", "pour trouver un edge honnête"))
    etat["sante"] = "tout fonctionne"
    # progression RÉELLE (FX-2) : position de la phase dans le cycle (l'état est réécrit à CHAQUE phase, donc ça
    # bouge), FUSIONNÉE avec la progression fine publiée par le moteur pendant un long calcul (progres_live).
    phases = list(CYCLE_PHASES)
    idx = (phases.index(phase) + 1) if phase in phases else 0
    ntot = len(phases)
    dc = float(etat.get("duree_cycle_s") or 0.0)
    vit_ph = round(idx / dc, 2) if (idx and dc > 0) else None
    eta_ph = round((ntot - idx) / vit_ph, 1) if (vit_ph and vit_ph > 0) else None
    try:
        import progres_live as PROG
        pg = PROG.lire()
    except Exception:  # noqa: BLE001
        pg = {}
    a_fin = bool(pg.get("total"))                            # le moteur publie une progression fine ?
    etat["ce_que_je_fais"] = {
        "je_fais": (pg.get("job") or phrase), "parce_que": pourquoi, "j_utilise": "recherche + tests + simulation",
        "fait": (pg.get("fait") if a_fin else idx), "total": (pg.get("total") if a_fin else ntot),
        "pourcentage": (pg.get("pourcentage") if a_fin else round(100.0 * idx / ntot, 1)),
        "vitesse": (pg.get("vitesse") if a_fin else vit_ph),
        "eta": (pg.get("eta") if a_fin else eta_ph),
        "ensuite": (pg.get("ensuite") or "tester d'autres réglages")}
    # système (psutil si dispo)
    try:
        import psutil  # type: ignore
        etat["systeme"] = {"cpu": psutil.cpu_percent(interval=0.0), "ram": psutil.virtual_memory().percent,
                           "disque": psutil.disk_usage(str(root)).percent, "workers": None,
                           "collecteurs": None, "bloquees": 0, "redemarrages": None, "erreurs": None}
    except Exception:  # noqa: BLE001
        etat["systeme"] = {}
    # simulation paper (depuis la réconciliation si déjà écrite)
    rec = None
    try:
        rec = json.loads((rundir / "results" / "reconciliation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = None
    etat["simulation"] = ({"capital": rec.get("capital_initial_usd"), "equity": rec.get("equity_usd"),
                           "pnl_realise": rec.get("pnl_realise_usd"), "pnl_net": rec.get("pnl_realise_usd"),
                           "roi_total": rec.get("roi_total_pct"), "roi_deploye": rec.get("roi_deploye_pct"),
                           "drawdown": rec.get("drawdown_usd")} if rec else {})
    # pépites (pistes intéressantes) + résultats
    etat["pepites"] = [{"candidate_id": p.get("candidate_id"), "explication": "%s %sms" % (p.get("coin"), p.get("horizon_ms")),
                        "net": p.get("net_bps"), "statut": p.get("statut")} for p in (interessantes or [])[:8]]
    etat["resultats_idees"] = {"pepites_possibles": len(interessantes or []), "rejetees": (etat.get("rejets") or {}).get("total")}
    # ── EST-CE LE BON MOMENT POUR CTRL+C ? (signaux RÉELS, FX-2 : durée live, candidats suivis, validations,
    #    gaps, jobs importants en cours, qualité du rapport — plus jamais le seul compte de cycles) ──
    ct = int(etat.get("cycles_termines") or 0)
    dcm = etat.get("duree", {})
    duree_min = int(dcm.get("jours", 0)) * 1440 + int(dcm.get("heures", 0)) * 60 + int(dcm.get("minutes", 0))
    try:
        import registre_candidats_live as RCL
        rcl = RCL.RegistreCandidatsLive(rundir).resume()
        n_suivis, n_pos = rcl.get("n_candidats", 0), rcl.get("n_positifs_live", 0)
    except Exception:  # noqa: BLE001
        n_suivis = n_pos = 0
    n_pass = int((tot or {}).get("n_pass", 0))
    try:
        import jobs_continue as JOBS
        jobs_running = JOBS.JobStore(rundir).compte().get("RUNNING", 0)
    except Exception:  # noqa: BLE001
        jobs_running = 0
    live = etat.get("donnees_live") or {}
    gaps = live.get("gaps")
    rapport_riche = (n_suivis > 0) or (n_pass > 0) or (ct >= 2)
    if jobs_running > 0:
        feu, msg = "🟡", "DES TESTS IMPORTANTS TOURNENT — mieux vaut les laisser finir"
    elif isinstance(gaps, (int, float)) and gaps > 0:
        feu, msg = "🟡", "DES TROUS DE DONNÉES RÉCENTS — le live n'est pas parfaitement continu"
    elif n_suivis == 0 and n_pass == 0 and duree_min < 5:
        feu, msg = "🔴", "TROP TÔT — peu de suivi live, rapport encore pauvre"
    elif rapport_riche:
        feu, msg = "🟢", "BON MOMENT — le rapport est déjà utile et stable"
    else:
        feu, msg = "🟡", "RAPPORT DÉJÀ UTILE, CONTINUER APPORTERA PLUS"
    etat["ctrl_c"] = {
        "feu": feu, "message": msg,
        "termine": "%d cycles · %d PASS · %d candidats suivis (%d positifs live)" % (ct, n_pass, n_suivis, n_pos),
        "manque": ("du suivi live" if n_suivis == 0 else ("laisser mûrir les positions" if n_pos == 0 else "rien de bloquant")),
        "tests_en_cours": (("%d job(s) en cours" % jobs_running) if jobs_running else etat.get("phase")),
        "duree_suivi": "%d min de live" % duree_min, "gaps": gaps,
        "stabilite": ("stable" if ct >= 2 else "jeune"),
        "qualite_rapport": ("riche" if rapport_riche else "encore mince"),
        "prochaine": "nouveau cycle de recherche", "eta_prochaine": None}
    # outils (dernier tableau écrit)
    try:
        camps = sorted((rundir / "campagnes").glob("camp-*"))
        ou = json.loads((camps[-1] / "resultats" / "outils_recherche.json").read_text(encoding="utf-8")) if camps else {}
        synth = bool(ou.get("synthetique"))                    # FX-3 : résultats synthétiques -> jamais dans les compteurs réels
        etat["outils"] = {"disponibles": ou.get("n_disponibles"),
                          "utilises": (None if synth else ou.get("n_lances")),
                          "actifs": (None if synth else ou.get("n_avec_trials_reels")),
                          "corpus_source": ou.get("corpus_source"),
                          "detail": ([("%s (SYNTHÉTIQUE — non compté)" % k) for k in (ou.get("outils") or {})]
                                     if synth else list((ou.get("outils") or {}).keys()))}
    except (OSError, ValueError):
        etat["outils"] = {}


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
def _dependances_optionnelles() -> dict:
    """État des dépendances d'optimisation OPTIONNELLES (FX-3). Absentes -> outils avancés indisponibles
    HONNÊTEMENT (grid/random/QMC-Halton restent toujours dispo). Voir requirements-recherche.txt."""
    etat = {}
    for mod in ("optuna", "cmaes", "scipy", "numpy"):
        try:
            __import__(mod)
            etat[mod] = "present"
        except Exception:  # noqa: BLE001
            etat[mod] = "absent"
    return {"paquets": etat, "requirements": "requirements-recherche.txt",
            "note": "optuna+cmaes activent TPE/CMA-ES/QMC/NSGA-II + pruners Hyperband/SuccessiveHalving ; absents = grid/random/QMC-Halton seuls (honnête)."}


def dry_run(root: Path) -> dict:
    root = Path(root)
    sec = SEC.auditer(root)
    dok, dmsg = CFG.disque_ok(str(root))
    return {"commande": "dry-run", "PASS": bool(sec["securise"] and dok),
            "securite": {"securise": sec["securise"], "fichiers": sec["fichiers_scannes"]},
            "disque": {"ok": dok, "detail": dmsg}, "ressources": CFG.limites(str(root)),
            "outils_optionnels": _dependances_optionnelles(),
            "mode": "CONTINU (sans limite de duree ; Ctrl+C = finalisation)",
            "securite_ligne": "0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · 0 depot/retrait"}


def _dernier_run_recuperable(root: Path) -> dict | None:
    """Dernier run sur disque (pour `resume` quand ACTIVE.json a disparu après un crash)."""
    runs = sorted(_run_root(root).glob("rcont-*"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    for r in reversed(runs):
        try:
            return json.loads((r / "run_identity.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def creer_ou_reprendre(root: Path, *, exiger_flux: bool = True, mode: str = "auto") -> dict:
    """`mode` : 'start' = crée un NOUVEAU run seulement s'il n'y en a pas d'actif (sinon demande) ;
    'resume' = reprend le run actif, ou le dernier récupérable après crash ; 'auto' = comportement historique."""
    root = Path(root)
    ident = _identite_active(root)
    if mode == "start" and ident:                            # START ≠ RESUME : ne pas reprendre en douce
        return {"start": "RUN_ACTIF_EXISTE", "run_id": ident["run_id"],
                "message": "Un laboratoire est déjà actif. Choisis 2 (Reprendre) ou arrête-le d'abord (5)."}
    if mode == "resume":
        rec = ident or _dernier_run_recuperable(root)
        if not rec:
            return {"start": "AUCUN_RUN_A_REPRENDRE"}
        if not ident:                                        # reprise après crash : on réarme ACTIVE.json
            _ecrire_atomique(_active_path(root), json.dumps(rec, ensure_ascii=False, indent=1))
        return {"start": "REPRISE", "run_id": rec["run_id"], "rundir": rec["rundir"], "reprise": True}
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
def _coherence_reconciliation(rundir: Path, glob: dict) -> tuple:
    """Cohérence RÉELLE (FX-7) : compare la reconstruction indépendante `glob` (depuis le ledger, en streaming)
    au SNAPSHOT persistant du portefeuille global (state.json) via PortefeuilleGlobal.reconcilier() qui recalcule
    cash/réalisé depuis SON ledger et les confronte à SON snapshot. `coherent` est CALCULÉ, jamais codé True.
    Rend (coherent, detail). coherent=None SEULEMENT s'il n'y a aucun portefeuille global (rien à vérifier)."""
    gp = Path(rundir) / "global_portfolio"
    if not (gp / "state.json").exists() and not (gp / "ledger.jsonl").exists():
        return None, {"verifie": False, "raison": "PAS_DE_PORTEFEUILLE_GLOBAL"}
    try:
        import portefeuille_global as PG
        rc = PG.PortefeuilleGlobal(gp).reconcilier()          # compare ledger reconstruit ↔ snapshot du portefeuille
        # On confronte DEUX reconstructions INDÉPENDANTES du MÊME ledger (doivent être identiques) : `glob`
        # (reconciliation_prod, streaming) vs les valeurs LEDGER du portefeuille. On NE compare PAS l'equity :
        # elle inclut le latent des positions restées ouvertes (FX-6), absent de la reconstruction streaming.
        cash_g, cash_led = float(glob.get("cash") or 0.0), float(rc.get("cash_ledger") or 0.0)
        pnl_g, pnl_led = float(glob.get("pnl_realise") or 0.0), float(rc.get("realized_ledger") or 0.0)
        ecart_cash, ecart_pnl = abs(cash_g - cash_led), abs(pnl_g - pnl_led)
        tol = 1e-2
        coherent = bool(rc.get("coherent")) and ecart_cash < tol and ecart_pnl < tol
        return coherent, {"verifie": True, "portefeuille_ledger_vs_snapshot": bool(rc.get("coherent")),
                          "ecart_cash_streaming_vs_ledger_usd": round(ecart_cash, 6),
                          "ecart_pnl_streaming_vs_ledger_usd": round(ecart_pnl, 6),
                          "cash_snapshot": rc.get("cash_snapshot"), "cash_ledger": rc.get("cash_ledger"),
                          "realized_snapshot": rc.get("realized_snapshot"), "realized_ledger": rc.get("realized_ledger"),
                          "positions_ouvertes": rc.get("positions_ouvertes"), "tolerance_usd": tol}
    except Exception as e:  # noqa: BLE001
        return False, {"verifie": False, "raison": "ERREUR:%s" % str(e)[:120]}


def _reconcilier(rundir: Path) -> dict:
    """RÉCONCILIATION RÉELLE (PT-10) : reconstruit le PnL depuis les LEDGERS D'ÉVÉNEMENTS des portefeuilles
    paper (OPEN/ADD/REDUCE/CLOSE), en streaming, par campagne, puis agrège. La somme des médianes n'est PAS un
    PnL. Agrège aussi les VRAIES exclusions. `coherent` compare la reconstruction au portefeuille sauvegardé."""
    import reconciliation_prod as RECO
    rundir = Path(rundir)
    camps = sorted((rundir / "campagnes").glob("camp-*")) if (rundir / "campagnes").exists() else []
    n_verdicts = n_pass = 0
    par_campagne = []
    # GR-2 : le PnL/ROI/DD GLOBAL provient EXCLUSIVEMENT du portefeuille GLOBAL (alimenté par le vrai live
    # CanonicalStore FWD_BOOK après freeze). S'il n'existe pas encore, le global est VIDE (capital intact) — on ne
    # RETOMBE JAMAIS sur les ledgers de campagne (pré-forward archive = diagnostic uniquement, jamais le PnL global).
    global_led = rundir / "global_portfolio" / "ledger.jsonl"
    ledgers = [global_led] if global_led.exists() else []
    glob = RECO.reconstruire_global(ledgers, equity_curve_out=(rundir / "results" / "equity_curve.jsonl"))
    for c in camps:
        led = c / "ledger" / "forward_portfolio.jsonl"
        if led.exists():
            rc = RECO.reconstruire_depuis_ledger(led)         # DIAGNOSTIC pré-forward (jamais agrégé au global)
            par_campagne.append({"campagne": c.name, "pre_forward_diagnostic": True,
                                 **{k: rc[k] for k in ("pnl_realise", "equity", "roi_total_pct")}})
        try:
            finals = json.loads((c / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))
            for f in finals:
                n_verdicts += 1
                if f.get("verdict") == "PASS_FORWARD_PAPER":
                    n_pass += 1
        except (OSError, ValueError):
            pass
    exclusions = RECO.agreger_exclusions(rundir)
    coherent, coherence = _coherence_reconciliation(rundir, glob)   # FX-7 : CALCULÉ (jamais True codé)
    rec = {"n_campagnes": len(camps), "n_verdicts": n_verdicts, "n_pass": n_pass,
           "capital_initial_usd": glob["capital_initial"], "pnl_realise_usd": glob["pnl_realise"],
           "equity_usd": glob["equity"], "drawdown_usd": glob["drawdown_usd"],
           "roi_total_pct": glob["roi_total_pct"], "roi_deploye_pct": glob["roi_deploye_pct"],
           "coherent": coherent, "coherence": coherence, "par_campagne": par_campagne[:50],
           "evenements": glob["evenements"], "n_exclusions": len(exclusions), "exclusions": exclusions[:100],
           "note": "PnL/ROI/DD = portefeuille GLOBAL live UNIQUEMENT (CanonicalStore FWD_BOOK après freeze) ; le pré-forward archive est diagnostic (par_campagne) et n'entre jamais dans le global. Vide = capital intact (aucun trade live). `coherent` = ledger reconstruit vs snapshot (None si aucun portefeuille global)."}
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
    partial = partial or _URGENCE.is_set()                   # 2e Ctrl+C déjà arrivé -> partiel d'emblée
    _checkpoint(rundir, int(ident.get("cycle_courant", 0)), "FINALIZE")
    rec = _reconcilier(rundir)                                # réconciliation PnL/ROI/equity/DD AVANT le rapport
    partial = partial or _URGENCE.is_set()                   # 2e Ctrl+C RELU pendant la finalisation (PT-8)
    incoherent = (rec.get("coherent") is False)              # FX-7 : ledger ≠ snapshot -> JAMAIS COMPLETE
    if incoherent:
        partial = True
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
    if _URGENCE.is_set() and not partial:                    # 2e Ctrl+C arrivé PENDANT la construction du rapport
        partial = True
        etat = "FINALIZATION_PARTIAL"
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


def _demarrer_ipc_stop_thread(root: Path, *, intervalle_s: float = 0.5) -> threading.Thread:
    """Thread IPC (PT-8) : surveille STOP_REQUEST.json et positionne _ARRET IMMÉDIATEMENT (arrêt coopératif
    même pendant un long calcul de pipeline). S'arrête dès que _ARRET est posé."""
    def loop():
        while not _ARRET.is_set():
            if _stop_request_present(root):
                _ARRET.set()
                break
            _ARRET.wait(intervalle_s)
    t = threading.Thread(target=loop, name="ipc-stop", daemon=True)
    t.start()
    return t


def _demarrer_dashboard_thread(root: Path, ident: dict, *, intervalle_s: float = 0.4) -> threading.Thread:
    """Dashboard VRAIMENT vivant (FINAL-13 + FX-2). Rich Live + Layout + Progress à ~3 rafraîchissements/s (repli
    texte si Rich absent), MÊME pendant un long calcul. Fusionne la progression fine publiée par le moteur
    (progres_live). La touche S appelle la VRAIE fonction snapshot et AFFICHE le chemin du fichier créé (pas une
    simple vue nommée « snapshot »). Nav 1-7 sans intercepter Ctrl+C."""
    rundir = Path(ident["rundir"])
    debut = ident.get("t0_wall_ms", time.time() * 1000) / 1000.0
    etat_ui = {"vue": "tout", "snapshot_msg": None}

    def _etat():
        etat = json.loads((rundir / "LIVE-RESEARCH-STATE.json").read_text(encoding="utf-8"))
        ecoule = time.time() - debut                        # horloge RÉELLE recalculée à chaque rafraîchi
        etat["duree"] = {"jours": int(ecoule // 86400), "heures": int(ecoule % 86400 // 3600),
                         "minutes": int(ecoule % 3600 // 60), "secondes": int(ecoule % 60)}
        try:                                                # fusion progression FINE live (même process)
            import progres_live as PROG
            pg = PROG.lire()
            if pg.get("total"):
                cj = dict(etat.get("ce_que_je_fais") or {})
                cj.update(fait=pg["fait"], total=pg["total"], pourcentage=pg["pourcentage"],
                          vitesse=pg["vitesse"], eta=pg["eta"], je_fais=(pg.get("job") or cj.get("je_fais")))
                etat["ce_que_je_fais"] = cj
        except Exception:  # noqa: BLE001
            pass
        if etat_ui["snapshot_msg"]:
            etat["dernier_checkpoint"] = etat_ui["snapshot_msg"]
        return etat

    def _touche(console=None):
        import dashboard_flow as DF
        ch = DF.lire_touche_non_bloquante()                 # sans intercepter Ctrl+C
        if ch is None:
            return
        if ch in ("s", "S"):                                # VRAIE fonction snapshot + chemin affiché (FX-2)
            try:
                res = snapshot(root)
                chemin = res.get("rapport") or res.get("snapshot") or res.get("chemin") or "(inconnu)"
                etat_ui["snapshot_msg"] = "snapshot créé : %s" % chemin
                if console is not None:
                    console.print("[green]Snapshot écrit :[/green] %s" % chemin)
                else:
                    print("\n[SNAPSHOT] écrit : %s" % chemin, flush=True)
            except Exception as e:  # noqa: BLE001
                etat_ui["snapshot_msg"] = "snapshot échoué : %s" % str(e)[:80]
            return
        v = DF.touche_vers_vue(ch)
        if v and v != "snapshot":
            etat_ui["vue"] = v

    def loop():
        import dashboard_flow as DF
        try:
            from rich.console import Console
            from rich.live import Live
            console = Console()
            with Live(DF.rendre_rich(_etat()), console=console, refresh_per_second=3, screen=False) as live:
                while not _ARRET.is_set():
                    try:
                        _touche(console)
                        live.update(DF.rendre_rich(_etat()))
                    except Exception:  # noqa: BLE001 — un afficheur ne casse jamais le moteur
                        pass
                    _ARRET.wait(intervalle_s)
            return
        except Exception:  # noqa: BLE001 — Rich indisponible -> repli texte
            pass
        while not _ARRET.is_set():                          # repli texte (sans Rich)
            try:
                _touche(None)
                print("\033c" + DF.rendre_texte(_etat(), vue=etat_ui["vue"]), flush=True)
            except Exception:  # noqa: BLE001
                pass
            _ARRET.wait(max(0.5, intervalle_s))

    t = threading.Thread(target=loop, name="dashboard-live", daemon=True)
    t.start()
    return t


def _collecteurs_lecture_seule(root: Path | None = None) -> dict:
    """Registre des collecteurs READ-ONLY nourrissant le live, SUPERVISÉS en Python (PID+create_time,
    anti-doublon au resume, restart individuel, arrêt explicite). ARGUMENTS CORRECTS (les CLI refusent un
    argument positionnel : microstructure=`--root`, ctx=`--root --poll-s 30`). Aucun n'exécute d'ordre."""
    r = str(root or RACINE)
    return {
        "lab-microstructure": ["tools/collecter_lab_microstructure.py", "--root", r],
        "lab-ctx": ["tools/collecter_lab_ctx.py", "--root", r, "--poll-s", "30"],
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


def _ecrire_dernier_run_lance(root: Path, run_id: str | None) -> None:
    """FX-1 : mémorise le run_id RÉELLEMENT lancé (au démarrage). Après le Ctrl+C, le pointeur ACTIVE.json est
    retiré à la finalisation ; ce fichier permet au CMD de vérifier LE MÊME run (SHA recalculés)."""
    if not run_id:
        return
    try:
        p = _run_root(root) / "DERNIER_RUN_LANCE.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(run_id), encoding="utf-8")
    except OSError:
        pass


def _lire_dernier_run_lance(root: Path) -> str:
    try:
        return (_run_root(root) / "DERNIER_RUN_LANCE.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _effacer_dernier_run_lance(root: Path) -> None:
    """GR-3 : efface le pointeur AVANT tout start/resume. Un démarrage qui échoue ne laisse donc jamais un
    ancien run_id que le CMD irait vérifier par erreur."""
    try:
        (_run_root(root) / "DERNIER_RUN_LANCE.txt").unlink()
    except OSError:
        pass


def demarrer_foreground(root: Path, *, exiger_flux: bool = True, max_cycles: int | None = None,
                        collecteurs: dict | None = None, afficher_live: bool = True, mode: str = "auto") -> dict:
    """Démarre le run et TRAVAILLE au premier plan jusqu'au Ctrl+C, puis finalise proprement (partiel si 2e
    Ctrl+C). `mode` distingue START (nouveau run) de RESUME (reprise). Le moteur N'est PAS détaché (sinon
    Ctrl+C ne contrôlerait pas la finalisation). Un Superviseur relance les collecteurs read-only en option."""
    root = Path(root)
    _ARRET.clear(); _URGENCE.clear()
    _effacer_dernier_run_lance(root)                         # GR-3 : jamais de pointeur périmé si le démarrage échoue
    r = creer_ou_reprendre(root, exiger_flux=exiger_flux, mode=mode)
    if r.get("start") in ("PRECHECK_ECHEC", "RUN_ACTIF_EXISTE", "AUCUN_RUN_A_REPRENDRE"):
        return r
    ident = _identite_active(root) or {}
    _ecrire_dernier_run_lance(root, ident.get("run_id"))     # FX-1 : run_id RÉELLEMENT lancé (le CMD vérifiera CE run)
    _installer_signal(root)
    sup = watch = None
    if collecteurs:                                          # supervision optionnelle (read-only), sinon rien
        try:
            import superviseur_continue as SUP
            sup = SUP.Superviseur(Path(ident["rundir"]), collecteurs, root=root)
            sup.demarrer_tous()                              # anti-doublon au resume (PID + create_time)
            watch = _demarrer_surveillance_thread(sup)       # restart individuel des collecteurs morts
        except Exception:  # noqa: BLE001
            sup = None
    dash = _demarrer_dashboard_thread(root, ident) if afficher_live else None
    ipc = _demarrer_ipc_stop_thread(root)                    # STOP_REQUEST -> _ARRET immédiat (arrêt coopératif)
    try:
        boucle_continue(root, stop_event=_ARRET, max_cycles=max_cycles, afficher=False)
    finally:
        if dash is not None:
            dash.join(timeout=3.0)
        ipc.join(timeout=2.0)
        if watch is not None:
            watch.join(timeout=3.0)
        if sup is not None:
            try:
                sup.arreter_tous()                           # arrêt EXPLICITE des collecteurs à la finalisation
            except Exception:  # noqa: BLE001
                pass
    return finaliser(root, partial=_URGENCE.is_set(), raison="ctrl-c")


def _verifier_manifeste_sha(man: Path, rundir: Path) -> dict:
    """RECALCULE réellement le SHA-256 de CHAQUE fichier listé au manifeste et le compare (FX-1) : la simple
    présence d'un dictionnaire `fichiers` NE prouve rien. Rend le détail (n_ok / manquants / divergents)."""
    try:
        m = json.loads(Path(man).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "erreur": "MANIFESTE_ILLISIBLE:%s" % str(e)[:80]}
    fichiers = m.get("fichiers") or {}
    if not fichiers:
        return {"ok": False, "erreur": "AUCUN_FICHIER_DANS_MANIFESTE"}
    rundir = Path(rundir)
    n_ok = n_manq = n_div = 0
    div = []
    for rel, sha_attendu in fichiers.items():
        cible = (rundir / rel.split("/", 1)[1]) if str(rel).startswith("__RAPPORT__/") else (rundir / rel)
        if not cible.exists():
            n_manq += 1
            if len(div) < 20:
                div.append({"fichier": rel, "cause": "MANQUANT"})
        elif _sha(cible) != sha_attendu:                     # SHA RECALCULÉ ≠ SHA du manifeste
            n_div += 1
            if len(div) < 20:
                div.append({"fichier": rel, "cause": "SHA_DIVERGENT"})
        else:
            n_ok += 1
    ok = bool(n_manq == 0 and n_div == 0 and n_ok > 0)
    return {"ok": ok, "n_verifies": len(fichiers), "n_ok": n_ok, "n_manquants": n_manq,
            "n_diverge": n_div, "divergences": div, "code_sha_manifeste": m.get("code_sha")}


def verifier_finalisation(root: Path, run_id: str | None = None) -> dict:
    """Le CMD ne déclare « terminé » que si le rapport ET le manifeste de CE run existent, que l'état est
    FINALIZATION_COMPLETE*, et que TOUS les SHA du manifeste sont RECALCULÉS et concordent (FX-1). Sans run_id :
    vérif globale (au moins un rapport+manifeste)."""
    root = Path(root)
    if run_id:
        dossier = root / "Rapports en continu" / run_id
        rapports = list(dossier.glob("RAPPORT-RECHERCHE-CONTINUE_*.md")) if dossier.exists() else []
        rundir = _run_root(root) / run_id
        man = rundir / "manifeste" / "SHA256_MANIFEST_FINAL.json"
        etat_ok = shas_ok = False
        verif = {}
        if man.exists():
            try:
                m = json.loads(man.read_text(encoding="utf-8"))
                etat_ok = str(m.get("etat", "")).startswith("FINALIZATION_COMPLETE")
            except (OSError, ValueError):
                etat_ok = False
            verif = _verifier_manifeste_sha(man, rundir)      # RECALCULE tous les SHA (pas une simple présence)
            shas_ok = bool(verif.get("ok"))
        ok = bool(rapports and man.exists() and etat_ok and shas_ok)
        return {"finalisation_confirmee": ok, "run_id": run_id, "rapport": bool(rapports),
                "manifeste": man.exists(), "etat_complete": etat_ok, "sha_presents": shas_ok,
                "sha_recalcule": verif}
    dossier = root / "Rapports en continu"
    rapports = list(dossier.rglob("RAPPORT-RECHERCHE-CONTINUE_*.md")) if dossier.exists() else []
    manifs = list(_run_root(root).rglob("SHA256_MANIFEST_FINAL.json"))
    return {"finalisation_confirmee": bool(rapports and manifs), "n_rapports": len(rapports), "n_manifestes": len(manifs)}


def _cli():
    ap = argparse.ArgumentParser(description="Laboratoire de recherche CONTINU (paper-only)")
    ap.add_argument("commande", choices=["dry-run", "start", "resume", "status", "snapshot", "stop",
                                         "verifier-finalisation", "run-id-actif", "dernier-run-lance"])
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    root = RACINE
    if a.commande == "dry-run":
        dr = dry_run(root)
        print(json.dumps(dr, ensure_ascii=False, indent=1))
        raise SystemExit(0 if dr.get("PASS") else 2)          # code 0 si PASS, non-nul sinon (P7)
    elif a.commande in ("start", "resume"):
        r = demarrer_foreground(root, collecteurs=_collecteurs_lecture_seule(root), mode=a.commande)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        raise SystemExit(0 if r.get("finalisation") or r.get("start") in ("OK", "REPRISE") else 3)
    elif a.commande == "status":
        print(json.dumps(statut(root), ensure_ascii=False, indent=1))
    elif a.commande == "snapshot":
        print(json.dumps(snapshot(root), ensure_ascii=False, indent=1))
    elif a.commande == "stop":
        print(json.dumps(stopper(root, a.run_id or ""), ensure_ascii=False, indent=1))
    elif a.commande == "run-id-actif":
        ident = _identite_active(root)
        print(ident["run_id"] if ident else "")
    elif a.commande == "dernier-run-lance":                   # FX-1 : run_id du dernier run LANCÉ (survit à la finalisation)
        print(_lire_dernier_run_lance(root))
    elif a.commande == "verifier-finalisation":
        v = verifier_finalisation(root, a.run_id)
        print(json.dumps(v, ensure_ascii=False))
        raise SystemExit(0 if v["finalisation_confirmee"] else 1)


if __name__ == "__main__":
    _cli()
