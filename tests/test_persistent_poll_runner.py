"""T44 — runner de poll persistant : séquence/gating, stop, absorption d'erreur,
overlap WS joint avant copy-run, schéma engine status, self-restart.
Fakes uniquement: aucun réseau, aucune vraie commande CLI. Read-only / paper-only."""

from __future__ import annotations

import json

from hl_observer.runtime.equity_history_store import read_equity_points
from hl_observer.runtime.persistent_poll_runner import (
    EXIT_SELF_RESTART,
    EXIT_STOP,
    PersistentPollRunner,
    RunnerConfig,
)


class _FakeProc:
    def __init__(self, journal, label):
        self._journal = journal
        self._label = label
    def wait(self, timeout=None):
        self._journal.append(f"join:{self._label}")
        return 0
    def kill(self):
        self._journal.append(f"kill:{self._label}")


def _mk(tmp_path, *, max_runs=1, overlap=False, restart_every=0, fail_labels=(), on_step=None):
    journal: list[str] = []
    cfg = RunnerConfig(
        root=tmp_path, interval_seconds=15, max_runs=max_runs,
        plans_every_polls=5, diagnostics_every_polls=5,
        restart_every_polls=restart_every, overlap_ws_scans=overlap,
    )

    def fake_invoke(argv):
        label = argv[0]
        journal.append(f"invoke:{label}")
        if on_step is not None:
            on_step(label)
        if label in fail_labels:
            return 1, f"{label} boom"
        return 0, f"ok_metric=1\ninline value_a=2 for {label}"

    def fake_popen(argv, stdout_file):
        # argv = [python, -u, -m, hl_observer, <command>, ...]
        label = argv[4]
        journal.append(f"spawn:{label}")
        stdout_file.write(f"{label.replace('-', '_')}_ws=1\n")
        return _FakeProc(journal, label)

    runner = PersistentPollRunner(
        cfg, invoke=fake_invoke, popen=fake_popen,
        sleep_fn=lambda s: journal.append(f"sleep:{s}"),
    )
    return runner, journal, cfg


def _invoked(journal):
    return [e.split(":", 1)[1] for e in journal if e.startswith("invoke:")]


def test_poll1_runs_everything_then_gating_skips(tmp_path):
    runner, journal, _ = _mk(tmp_path, max_runs=6)
    assert runner.run() == EXIT_STOP
    seq = _invoked(journal)
    # poll 1: plans + collect refresh (explorer) + diagnostics presents
    assert "throughput-plan" in seq and "simulation-readiness" in seq
    assert "scrape-explorer" in seq and "explorer-candidates" in seq
    # copy-run et analyse a CHAQUE poll
    assert seq.count("copy-run") == 6
    assert seq.count("opportunity-report") == 6
    assert seq.count("fusion-heartbeat-input") == 6
    # plans/diagnostics: poll 1 et poll 5 uniquement (1 sur 5)
    assert seq.count("throughput-plan") == 2
    assert seq.count("simulation-readiness") == 2
    # ecoutes WS in-process en mode sequentiel (pas d'overlap)
    assert seq.count("live-user-fills-scan") == 6


def test_overlap_ws_scans_joined_before_copy_run(tmp_path):
    runner, journal, _ = _mk(tmp_path, max_runs=1, overlap=True)
    assert runner.run() == EXIT_STOP
    # spawn au debut, join AVANT copy-run (dependance fills -> decision)
    spawn_idx = journal.index("spawn:live-user-fills-scan")
    join_idx = journal.index("join:live-user-fills-scan")
    copy_idx = journal.index("invoke:copy-run")
    assert spawn_idx < join_idx < copy_idx
    # le scan public aussi est parallele
    assert "spawn:live-public-scan" in journal
    # et jamais invoque in-process en mode overlap
    assert "invoke:live-public-scan" not in journal
    # les metrics des ecoutes paralleles sont bien recuperees depuis leur sortie
    assert runner.metrics.get("live-user-fills-scan_live_user_fills_scan_ws") == "1" or any(
        k.startswith("live_user_fills_scan") or "live_user_fills_scan" in k for k in runner.metrics
    )


def test_stop_file_honored_between_polls(tmp_path):
    stop_after = {"done": False}
    def on_step(label):
        if label == "copy-run" and not stop_after["done"]:
            stop_after["done"] = True
            (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
            (tmp_path / "runtime" / "data" / "hypersmart_runtime.stop").touch()
    runner, journal, _ = _mk(tmp_path, max_runs=10, on_step=on_step)
    assert runner.run() == EXIT_STOP
    assert _invoked(journal).count("copy-run") == 1  # arret apres le poll 1


def test_failing_step_absorbed_loop_continues(tmp_path):
    runner, journal, _ = _mk(tmp_path, max_runs=2, fail_labels={"opportunity-report"})
    assert runner.run() == EXIT_STOP
    seq = _invoked(journal)
    assert seq.count("opportunity-report") == 2      # toujours tente
    assert seq.count("fusion-heartbeat-input") == 2  # la suite tourne quand meme
    assert runner.metrics.get("step_failed_opportunity_report") == "1"


def test_engine_status_schema_does_not_preserve_unstamped_fusion(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    pre = {"updated_at_ms": 1, "phase": "old", "fusion_runtime_input": {"votes": 3},
           "metrics": {"fusion_runtime_votes": "3"}}
    (tmp_path / "runtime" / "data" / "hypersmart_engine_status.json").write_text(
        json.dumps(pre), encoding="utf-8")
    runner, _, cfg = _mk(tmp_path, max_runs=1)
    assert runner.run() == EXIT_STOP
    status = json.loads(cfg.engine_status_path.read_text(encoding="utf-8"))
    for key in ("updated_at_ms", "phase", "poll_index", "max_runs", "metrics"):
        assert key in status
    assert status["read_only"] is True
    assert status["simulation_only"] is True
    assert status["external_action"] is False
    assert "fusion_runtime_input" not in status
    assert status["fusion_runtime_input_status"] == "STALE"
    assert "fusion_runtime_votes" not in status["metrics"]
    assert status["metrics"]["loop_mode"] == "persistent_t44"
    assert "poll_total_ms" in status["metrics"]
    assert any(k.startswith("step_ms_") for k in status["metrics"])


def test_self_restart_exit_code(tmp_path):
    runner, journal, _ = _mk(tmp_path, max_runs=10, restart_every=2)
    assert runner.run() == EXIT_SELF_RESTART
    assert _invoked(journal).count("copy-run") == 2  # exactement 2 polls avant rotation


def test_runner_uses_canonical_session_baseline_not_hardcoded_1000(tmp_path):
    runner, _, cfg = _mk(tmp_path, max_runs=1)
    runner._session_id = "paper:baseline-1250"
    runner.metrics["fusion_runtime_starting_equity_usdt"] = "1250"
    runner.metrics["fusion_runtime_current_equity_usdt"] = "1275"

    runner.write_engine_status("sleeping", "test")

    point = read_equity_points(runtime_data_dir=cfg.runtime_data_dir)[-1]
    assert point["starting_equity_usdt"] == 1250.0
    assert point["equity"] == 1275.0
    assert point["pnl"] == 25.0


def test_runner_never_invents_pnl_when_session_baseline_is_missing(tmp_path):
    runner, _, cfg = _mk(tmp_path, max_runs=1)
    runner._session_id = "paper:no-baseline"
    runner.metrics["fusion_runtime_current_equity_usdt"] = "1275"

    runner.write_engine_status("sleeping", "test")

    point = read_equity_points(runtime_data_dir=cfg.runtime_data_dir)[-1]
    assert point["equity"] == 1275.0
    assert point["pnl"] is None
    assert point["accounting_status"] == "BASELINE_UNMEASURABLE"
