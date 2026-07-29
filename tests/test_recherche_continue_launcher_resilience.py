"""Regression tests for the long-running continuous-research launcher."""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import champions_continue as CH  # noqa: E402
import curseurs_continue as CUR  # noqa: E402
import dashboard_flow as DF  # noqa: E402
import familles_continue as FAM  # noqa: E402
import heartbeat_collecteur as HB  # noqa: E402
import moteur_execution_prod as MEP  # noqa: E402
import pipeline_18h as PL  # noqa: E402
import progres_live as PROG  # noqa: E402
import rapport_arret_continue as RAC  # noqa: E402
import recherche_continue as RC  # noqa: E402
import scheduler_continue as SCH  # noqa: E402
import superviseur_continue as SUP  # noqa: E402


def _episode(i: int) -> dict:
    mid = 100.0 + i * 0.0001
    return {
        "coin": "BTC",
        "ts_ms": i,
        "bid": mid - 0.01,
        "ask": mid + 0.01,
        "fwd_bid": {250: mid + 0.02},
        "fwd_ask": {250: mid + 0.04},
    }


def test_progression_exposes_global_and_inner_loop_metrics():
    PROG.reset(4, job="replay")
    PROG.publier(
        1,
        4,
        detail="exact replay",
        traite=50,
        traite_total=100,
        unite="events",
    )
    state = PROG.lire()
    assert state["pourcentage"] == 37.5
    assert state["traite"] == 50
    assert state["traite_total"] == 100
    assert state["detail"] == "exact replay"
    assert state["age_maj_s"] is not None
    assert state["duree_s"] is not None
    assert state["statut_progression"] == "ACTIF"
    assert state["journal"]
    assert state["sequence"] >= 1


def test_progression_journal_is_bounded_and_tracks_major_steps():
    PROG.reset(40, job="discovery", ensuite="validation")
    for index in range(40):
        PROG.publier(
            index,
            40,
            job="discovery",
            detail=f"variant {index}",
            traite=index * 10,
            traite_total=400,
        )
    state = PROG.lire()
    assert len(state["journal"]) <= 16
    assert state["journal"][-1]["sequence"] == state["sequence"]
    assert any("Etape" in item["message"] for item in state["journal"])


def test_exact_replay_honors_stop_inside_large_corpus():
    class StopAfterSecondProbe:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls >= 2

    corpus = [_episode(i) for i in range(10_000)]
    result = MEP.evaluer_episodes(
        corpus,
        sens=1,
        horizon_ms=250,
        stop_event=StopAfterSecondProbe(),
        progress_every=128,
    )
    assert 0 < len(result) < len(corpus)
    assert len(result) <= 1024


def test_discovery_reuses_identical_filtered_subcorpus(tmp_path, monkeypatch):
    corpus = [_episode(i) for i in range(50)]
    variants = [
        {
            "family": "GENERIC",
            "coin": "BTC",
            "horizon_ms": 250,
            "regime": None,
            "direction": direction,
            "params": {"seuil": 8},
        }
        for direction in (1, -1)
    ]
    calls = {"filter": 0, "screen": 0}
    original_filter = PL._filtrer_corpus

    def counted_filter(*args, **kwargs):
        calls["filter"] += 1
        return original_filter(*args, **kwargs)

    def fast_screen(*args, **kwargs):
        calls["screen"] += 1
        return {"garder": False, "net_approx_bps": -1.0, "interrompu": False}

    monkeypatch.setattr(PL, "_filtrer_corpus", counted_filter)
    monkeypatch.setattr(PL, "fast_screen_variante", fast_screen)
    monkeypatch.setattr(PL.REG, "preenregistrer", lambda *args, **kwargs: None)
    monkeypatch.setattr(PL.REG, "enregistrer_resultat", lambda *args, **kwargs: None)

    result = PL.phase_discovery(
        tmp_path,
        corpus,
        variants,
        code_sha="abc",
        source_hash="source",
    )
    assert result["n_fast_screen"] == 2
    assert calls == {"filter": 1, "screen": 2}


def test_cycle_stops_before_post_processing_after_ctrl_c(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stop = threading.Event()
    downstream_calls = []
    variant = {
        "family": "GENERIC",
        "coin": "BTC",
        "horizon_ms": 250,
        "regime": None,
        "direction": 1,
        "params": {"seuil": 8},
    }

    monkeypatch.setattr(
        RC,
        "_scanner_nouveautes",
        lambda *args, **kwargs: {
            "new_events": [],
            "n_new": 0,
            "sources_avec_nouveaute": 0,
        },
    )
    monkeypatch.setattr(CUR, "fenetres_impactees", lambda *args, **kwargs: {"coins": []})
    monkeypatch.setattr(FAM, "horizons_pour", lambda *args, **kwargs: [250])
    monkeypatch.setattr(RC, "_variantes_du_cycle", lambda *args, **kwargs: ([variant], set()))
    monkeypatch.setattr(
        SCH,
        "planifier_cycle",
        lambda *args, **kwargs: {"files_consommees": []},
    )
    monkeypatch.setattr(CH, "charger", lambda *args, **kwargs: [])
    monkeypatch.setattr(RC, "_maturer_live", lambda *args, **kwargs: ([], {}))
    monkeypatch.setattr(RC, "_securite_run", lambda *args, **kwargs: True)
    monkeypatch.setattr(RC, "_sauver_signatures", lambda *args, **kwargs: None)
    monkeypatch.setattr(RC, "_checkpoint", lambda *args, **kwargs: None)

    def interrupted_pipeline(*args, **kwargs):
        stop.set()
        return {"n_preregistres": 0}

    monkeypatch.setattr(PL, "executer_pipeline_donnees_completes", interrupted_pipeline)

    def forbidden(name):
        def call(*args, **kwargs):
            downstream_calls.append(name)
            return {}

        return call

    monkeypatch.setattr(RC, "_enregistrer_champions", forbidden("champions"))
    monkeypatch.setattr(RC, "_travail_de_fond", forbidden("background"))
    monkeypatch.setattr(RC, "_outils_recherche", forbidden("optimizers"))
    monkeypatch.setattr(RC, "_suivi_candidats_live", forbidden("live-follow"))

    result = RC.executer_cycle(
        tmp_path,
        run_dir,
        cycle=1,
        code_sha="abc",
        stop_event=stop,
    )
    assert result["interrompu"] is True
    assert result["jobs"]["ignores_apres_arret"] is True
    assert downstream_calls == []


def test_continuous_loop_recovers_after_a_cycle_error(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ident = {
        "run_id": "test-recovery",
        "rundir": str(run_dir),
        "cycle_courant": 0,
        "code_sha": "abc",
    }
    calls = {"cycles": 0}

    monkeypatch.setattr(RC, "_identite_active", lambda root: ident)
    monkeypatch.setattr(RC, "_stop_request_present", lambda root: False)
    monkeypatch.setattr(RC, "CYCLE_PHASES", ("DISCOVERY",))
    monkeypatch.setattr(RC, "construire_etat", lambda *args, **kwargs: {})

    def fail_once(*args, **kwargs):
        calls["cycles"] += 1
        if calls["cycles"] == 1:
            raise RuntimeError("temporary cycle error")
        return {}

    monkeypatch.setattr(RC, "executer_cycle", fail_once)
    result = RC.boucle_continue(
        tmp_path,
        max_cycles=1,
        intervalle_s=0.01,
        recovery_backoff_s=0.01,
    )
    errors = (run_dir / "results" / "RUN-ERRORS.jsonl").read_text(encoding="utf-8")
    assert result["boucle"] == "MAX_CYCLES"
    assert calls["cycles"] == 2
    assert "temporary cycle error" in errors
    assert '"phase": "DISCOVERY"' in errors


def test_dashboard_shows_inner_progress_and_final_report():
    state = {
        "duree": {"jours": 0, "heures": 1, "minutes": 2, "secondes": 3},
        "ce_que_je_fais": {
            "je_fais": "replay exact",
            "detail": "variant 3/48",
            "parce_que": "validate signal",
            "pourcentage": 12.5,
            "fait": 2,
            "total": 7,
            "vitesse": 0.2,
            "eta": 25,
            "traite": 500,
            "traite_total": 1000,
            "unite": "events",
            "debit_interne": 250.0,
            "age_maj_s": 0.2,
            "duree_progression_s": 2.0,
            "ensuite": "validation",
        },
        "totaux": {"testees": 1},
        "resultats_idees": {},
        "simulation": {},
        "supervision": {
            "etat_ui": "ACTIF",
            "etat_moteur": "ACTIF",
            "ui_tick": 42,
            "intervalle_ms": 250,
            "age_progression_s": 0.2,
            "erreurs_rendu": 0,
            "heure": "12:34:56",
            "journal": [{"heure": "12:34:55", "niveau": "ETAPE", "message": "Replay lancé"}],
        },
        "finalisation": {
            "pourcentage": 50,
            "etape": "report",
            "rapport": r"C:\report.md",
        },
    }
    rows = dict(DF.construire_vue_compacte(state))
    assert "12.500%" in rows["Progression"]
    assert "500/1 000 events" in rows["Progression interne"]
    assert rows["Rapport"] == r"C:\report.md"
    assert "compteur il y a" in rows["Dernière activité"].lower()
    assert "image 42" in rows["Supervision UI"]
    assert rows["État moteur"].startswith("ACTIF")
    assert DF.rendre_rich(state).__class__.__name__ == "Layout"


def test_dashboard_stays_visible_only_while_finalization_is_running(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ident = {
        "run_id": "test-finalization",
        "rundir": str(run_dir),
        "t0_wall_ms": time.time() * 1000,
    }
    RC._ARRET.clear()
    RC._FINALISATION_DEMARREE.clear()
    RC._FINALISATION_TERMINEE.clear()
    thread = RC._demarrer_dashboard_thread(tmp_path, ident, intervalle_s=0.02)
    try:
        RC._FINALISATION_DEMARREE.set()
        RC._ARRET.set()
        time.sleep(0.1)
        assert thread.is_alive()
    finally:
        RC._FINALISATION_TERMINEE.set()
        thread.join(timeout=2.0)
        RC._FINALISATION_DEMARREE.clear()
        RC._FINALISATION_TERMINEE.clear()
        RC._ARRET.clear()
    assert not thread.is_alive()


def test_dashboard_writes_a_heartbeat_each_second(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ident = {
        "run_id": "test-heartbeat",
        "rundir": str(run_dir),
        "t0_wall_ms": time.time() * 1000,
    }
    RC._ARRET.clear()
    RC._FINALISATION_DEMARREE.clear()
    RC._FINALISATION_TERMINEE.clear()
    thread = RC._demarrer_dashboard_thread(tmp_path, ident, intervalle_s=0.1)
    heartbeat_path = run_dir / "DASHBOARD-HEARTBEAT.json"
    try:
        deadline = time.time() + 2.0
        while not heartbeat_path.exists() and time.time() < deadline:
            time.sleep(0.02)
        first = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        time.sleep(1.1)
        second = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        assert first["etat_ui"] == "ACTIF"
        assert second["ui_tick"] > first["ui_tick"]
        assert second["ts"] > first["ts"]
        assert thread.is_alive()
    finally:
        RC._FINALISATION_TERMINEE.set()
        thread.join(timeout=2.0)
        RC._FINALISATION_DEMARREE.clear()
        RC._FINALISATION_TERMINEE.clear()
        RC._ARRET.clear()


def test_dashboard_survives_a_temporary_rich_render_error(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ident = {
        "run_id": "test-render-recovery",
        "rundir": str(run_dir),
        "t0_wall_ms": time.time() * 1000,
    }
    original = DF.rendre_rich
    calls = {"count": 0}

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary renderer failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(DF, "rendre_rich", flaky)
    RC._ARRET.clear()
    RC._FINALISATION_DEMARREE.clear()
    RC._FINALISATION_TERMINEE.clear()
    thread = RC._demarrer_dashboard_thread(tmp_path, ident, intervalle_s=0.05)
    try:
        deadline = time.time() + 2.0
        error_path = run_dir / "results" / "DASHBOARD-UI-ERRORS.log"
        while not error_path.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert "temporary renderer failure" in error_path.read_text(encoding="utf-8")
        assert thread.is_alive()
    finally:
        RC._FINALISATION_TERMINEE.set()
        thread.join(timeout=2.0)
        RC._FINALISATION_DEMARREE.clear()
        RC._FINALISATION_TERMINEE.clear()
        RC._ARRET.clear()


def test_supervisor_adopts_existing_collector_without_spawning(tmp_path, monkeypatch):
    supervisor = SUP.Superviseur(
        tmp_path / "run",
        {"collector": ["tools/collector.py"]},
        root=tmp_path,
    )
    monkeypatch.setattr(
        supervisor,
        "_processus_du_script",
        lambda name: [{"pid": 1234, "start": 42.0, "script": "collector.py"}],
    )

    def must_not_spawn(*args, **kwargs):
        raise AssertionError("existing collector must be adopted")

    result = supervisor.demarrer_un("collector", lancer=must_not_spawn)
    assert result["etat"] == "ADOPTE_EXISTANT"
    assert result["pid"] == 1234
    assert supervisor.etat["collector"]["adopte_processus_existant"] is True


def test_concurrent_heartbeats_remain_valid_and_leave_no_shared_tmp(tmp_path):
    def write(i):
        return HB.battre(tmp_path, "collector", n_ecrites=1, note=str(i))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(80)))

    heartbeat = HB.lire(tmp_path, "collector")
    assert len(results) == 80
    assert heartbeat["nom"] == "collector"
    assert heartbeat["pid"] > 0
    assert heartbeat["n_passes"] >= 1
    assert not list(HB.chemin(tmp_path, "collector").parent.glob("*.tmp"))


def test_cmd_preserves_run_pointer_and_exposes_diagnostics():
    content = (ROOT / "LANCER-RECHERCHE-CONTINUE.cmd").read_text(
        encoding="utf-8",
        errors="ignore",
    ).lower()
    assert 'cd /d "%~dp0"' in content
    assert "python -u tools\\recherche_continue.py dry-run" in content
    assert "verifier-finalisation" in content
    assert "dernier-run-lance" in content
    assert "del " not in content
    assert "dernier_run_lance.txt" not in content
    assert "dry-run >nul" not in content
    assert "hypersmart_dashboard_fullscreen=1" in content
    assert "hypersmart_dashboard_refresh_ms=1000" in content
    assert "hypersmart_resource_priority=below_normal" in content
    assert "hypersmart_resource_never_idle=1" in content


def test_dashboard_exposes_non_idle_resource_policy():
    state = {
        "totaux": {},
        "resultats_idees": {},
        "simulation": {},
        "resource_policy": {
            "priority": "BELOW_NORMAL",
            "never_idle": True,
            "pause_workload": False,
            "salad_active": True,
            "max_workers": 1,
            "max_sources_per_bootstrap": 64,
            "max_bootstrap_megabytes": 128,
        },
    }
    rows = dict(DF.construire_vue_compacte(state))
    assert "BELOW_NORMAL permanent" in rows["Ressources"]
    assert "jamais Idle" in rows["Ressources"]
    assert "aucune pause" in rows["Ressources"]
    assert "Salad actif" in rows["Ressources"]


def test_shutdown_report_preserves_an_interrupted_campaign(tmp_path):
    run_dir = tmp_path / "run"
    campaign_dir = run_dir / "campagnes" / "camp-0001-test"
    results = run_dir / "results"
    canonical = run_dir / "canonical"
    campaign_dir.mkdir(parents=True)
    results.mkdir(parents=True)
    canonical.mkdir(parents=True)
    (campaign_dir / "campaign.json").write_text(
        json.dumps({
            "campaign_id": "camp-0001-test",
            "cycle": 1,
            "n_new_events": 100_000,
            "sources_avec_nouveaute": 12,
            "n_variantes_nouvelles": 48,
        }),
        encoding="utf-8",
    )
    (campaign_dir / "scheduler_state.json").write_text(
        json.dumps({
            "files_consommees": ["ingestion_sante", "exploration_familles"],
            "toutes_consommees": False,
        }),
        encoding="utf-8",
    )
    source = tmp_path / "source.jsonl"
    source.write_text("{}\n" * 10, encoding="utf-8")
    (run_dir / "cursors.json").write_text(
        json.dumps({
            str(source): {
                "offset": 15,
                "taille": 30,
                "n_nouveaux": 10,
                "rotation": False,
            }
        }),
        encoding="utf-8",
    )
    (canonical / "maturation.json").write_text(
        json.dumps({"maries": 90_000, "consommes": 80_000, "expires": 5_000, "backlog": 5_000}),
        encoding="utf-8",
    )
    (results / "RUN-ERRORS.jsonl").write_text(
        json.dumps({
            "ts": time.time(),
            "cycle": 1,
            "phase": "INDEXATION",
            "type": "PermissionError",
            "erreur": "atomic replace refused",
        }) + "\n",
        encoding="utf-8",
    )
    (results / "FINAL-INTERRUPTION-CONTEXT.json").write_text(
        json.dumps({
            "reason": "ctrl-c",
            "signal_count": 1,
            "cycle": 1,
            "phase": "INDEXATION",
            "progress": {
                "job": "rejeu exact",
                "pourcentage": 28.571,
                "fait": 2,
                "total": 7,
                "traite": 25_000,
                "traite_total": 100_000,
                "eta": 30,
            },
        }),
        encoding="utf-8",
    )
    (results / "data_source_accounting.csv").write_text(
        "source,statut\none,PARSED\n",
        encoding="utf-8",
    )
    (results / "data_source_exclusions.csv").write_text(
        "source,raison\nbad,INVALID\n",
        encoding="utf-8",
    )
    summary = RAC.collecter(
        run_dir,
        {
            "run_id": "rcont-test",
            "code_sha": "abc",
            "cycle_courant": 1,
            "t0_wall_ms": (time.time() - 60) * 1000,
            "read_only": True,
            "real_execution": False,
        },
    )
    markdown = RAC.markdown(summary)
    assert summary["campaign_totals"]["new_events"] == 100_000
    assert summary["campaigns"][0]["status"] == "IN_PROGRESS_OR_INTERRUPTED"
    assert summary["cursors"]["coverage_pct"] == 50.0
    assert summary["runtime_errors"]["rows_total"] == 1
    assert "100000événements" in markdown.replace(" ", "")
    assert "IN_PROGRESS_OR_INTERRUPTED" in markdown
    assert "PermissionError" in markdown
    for name in (
        "FINAL-RUN-SUMMARY.json",
        "FINAL-CAMPAIGN-STATUS.csv",
        "FINAL-ERRORS.csv",
        "FINAL-ARTIFACT-INVENTORY.csv",
        "FINAL-CURSOR-COVERAGE.csv",
    ):
        assert (results / name).exists(), name


def test_stop_context_keeps_the_first_signal_snapshot(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "campagnes" / "camp-0001-test").mkdir(parents=True)
    (run_dir / "LIVE-RESEARCH-STATE.json").write_text(
        json.dumps({"cycle": 1, "phase": "DISCOVERY"}),
        encoding="utf-8",
    )
    ident = {
        "run_id": "rcont-stop",
        "cycle_courant": 1,
        "read_only": True,
        "real_execution": False,
    }
    RC._SIGNAL_COUNT = 1
    PROG.reset(7, job="discovery")
    PROG.publier(2, 7, detail="first state", traite=10, traite_total=100)
    path = RC._capturer_contexte_arret(
        run_dir,
        ident,
        raison="ctrl-c",
        partial=False,
    )
    first = json.loads(path.read_text(encoding="utf-8"))
    PROG.publier(6, 7, detail="finalization", traite=90, traite_total=100)
    RC._capturer_contexte_arret(
        run_dir,
        ident,
        raison="ctrl-c",
        partial=False,
        final_state={"stage": "SAFETY_AUDIT_COMPLETE", "security_ok": True},
    )
    second = json.loads(path.read_text(encoding="utf-8"))
    assert first["initial_capture"]["progress"]["fait"] == 2
    assert second["initial_capture"]["progress"]["fait"] == 2
    assert second["latest_progress"]["fait"] == 6
    assert second["final_state"]["security_ok"] is True
    assert second["signal_count"] == 1
    RC._SIGNAL_COUNT = 0


def test_ctrl_c_handler_requests_clean_then_emergency_stop(monkeypatch, tmp_path):
    captured = {}

    def fake_signal(sig, handler):
        captured["sig"] = sig
        captured["handler"] = handler

    monkeypatch.setattr(RC.signal, "signal", fake_signal)
    RC._ARRET.clear()
    RC._URGENCE.clear()
    RC._SIGNAL_COUNT = 0
    try:
        RC._installer_signal(tmp_path)
        assert captured["sig"] == RC.signal.SIGINT

        captured["handler"](RC.signal.SIGINT, None)
        assert RC._ARRET.is_set()
        assert not RC._URGENCE.is_set()
        assert RC._SIGNAL_COUNT == 1

        captured["handler"](RC.signal.SIGINT, None)
        assert RC._URGENCE.is_set()
        assert RC._SIGNAL_COUNT == 2
    finally:
        RC._ARRET.clear()
        RC._URGENCE.clear()
        RC._SIGNAL_COUNT = 0
