from __future__ import annotations

import json
import sys
from pathlib import Path

from hl_observer.ops.historical_analysis_suite import (
    AnalysisStage,
    StageResult,
    build_stage_plan,
    run_stage,
    run_suite,
)

ROOT = Path(__file__).resolve().parents[1]


def test_standard_plan_covers_replay_backtest_ab_and_diagnostics(tmp_path):
    plan = build_stage_plan(tmp_path, tmp_path / "out")
    keys = [stage.key for stage in plan]
    assert keys == [
        "merge_replay",
        "pnl_improvement_lab",
        "replay_data_quality",
        # RECABLAGE : la chaine market_truth (canonicalisation -> replay executable
        # -> ledger reconcilie) etait testee mais sans aucun appelant. Elle est
        # desormais une etape a part entiere du lanceur d'analyse officiel.
        "market_truth_replay",
        "lead_lag_shadow",
        "ab_exact",
        "realtime_replay",
        "closed_ledger_replay",
        "strategy_tournament",
        "pnl_audit",
        "loss_attribution",
        "latency_report",
        "freshness_diagnostics",
    ]
    command_text = "\n".join(" ".join(stage.command) for stage in plan)
    ab_command = next(stage.command for stage in plan if stage.key == "ab_exact")
    assert "--network-read" not in command_text
    assert "/exchange" not in command_text
    assert "scenario_search" not in keys
    assert "--notional-usd" in ab_command
    assert ab_command[ab_command.index("--notional-usd") + 1] == "50"
    assert "--cache-path" in ab_command


def test_deep_plan_is_explicit_and_keeps_standard_stages(tmp_path):
    plan = build_stage_plan(tmp_path, tmp_path / "out", deep=True)
    keys = [stage.key for stage in plan]
    assert "walk_forward" in keys
    assert "anti_overfit" in keys
    assert keys[-1] == "scenario_search"
    assert plan[-1].optional is True
    assert plan[-1].timeout_seconds >= 7_200


def test_stage_with_missing_local_data_is_skipped_without_subprocess(tmp_path):
    stage = AnalysisStage(
        key="missing",
        title="Missing",
        purpose="test",
        command=(sys.executable, "-c", "raise SystemExit(99)"),
        required_paths=(tmp_path / "absent.jsonl",),
        timeout_seconds=60,
    )
    result = run_stage(stage, root=tmp_path, output_dir=tmp_path / "reports")
    assert result.status == "SKIPPED"
    assert result.return_code is None
    assert "absent.jsonl" in result.message
    assert Path(result.log_path).exists()


def test_stage_captures_real_subprocess_output(tmp_path):
    stage = AnalysisStage(
        key="probe",
        title="Probe",
        purpose="test",
        command=(sys.executable, "-c", "print('analysis-ok')"),
        timeout_seconds=60,
    )
    result = run_stage(stage, root=tmp_path, output_dir=tmp_path / "reports")
    assert result.status == "PASSED"
    assert result.return_code == 0
    assert "analysis-ok" in Path(result.log_path).read_text(encoding="utf-8")


def test_suite_always_writes_consolidated_json_and_markdown(tmp_path):
    def fake_runner(stage, *, root, output_dir):
        log_path = output_dir / f"{stage.key}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok\n", encoding="utf-8")
        return StageResult(
            key=stage.key,
            title=stage.title,
            status="PASSED",
            return_code=0,
            duration_seconds=0.01,
            log_path=str(log_path),
            message="Etape terminee.",
            command=stage.command,
        )

    code, report_path, results = run_suite(tmp_path, stage_runner=fake_runner)
    assert code == 0
    assert len(results) == 13
    assert report_path.exists()
    latest = tmp_path / "runtime" / "reports" / "backtest_replay" / "RAPPORT_LATEST.md"
    latest_json = tmp_path / "runtime" / "reports" / "backtest_replay" / "report_latest.json"
    assert latest.exists()
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload["local_data_only"] is True
    assert payload["network_used"] is False
    assert payload["real_execution"] is False
    assert payload["summary"]["PASSED"] == 13


def test_consolidated_report_surfaces_pnl_findings(tmp_path):
    from hl_observer.ops.historical_analysis_suite import write_reports

    output_dir = tmp_path / "runtime" / "reports" / "backtest_replay" / "run"
    output_dir.mkdir(parents=True)
    (output_dir / "pnl_improvement_lab.json").write_text(
        json.dumps(
            {
                "automatic_activation": False,
                "truth": {
                    "all_paired": {
                        "trades": 40,
                        "net_pnl_actual_usdc": -4.0,
                        "profit_factor_actual": 0.8,
                    },
                    "eligible_for_learning": {
                        "trades": 32,
                        "net_pnl_actual_usdc": 1.5,
                        "profit_factor_actual": 1.2,
                    },
                },
                "temporal_validation": {"status": "COMPLETED"},
                "quality": {"paired_round_trips": 40},
                "groups": {
                    "by_exit_method": [
                        {
                            "group": "SLTP_STOP_LOSS",
                            "trades": 8,
                            "net_pnl_actual_usdc": -2.5,
                            "profit_factor_actual": 0.4,
                            "normalized_net_usdc": -1.2,
                            "fees_reported_usdc": 0.8,
                        }
                    ],
                    "by_coin": [],
                },
                "findings": {
                    "robust_opportunities": ["Consensus >= 3"],
                    "needs_confirmation": [],
                    "rejected_hypotheses": ["LONG uniquement"],
                    "missing_evidence": ["liquidity_score incomplet"],
                    "next_exact_ab_experiments": ["Rejouer le consensus"],
                },
                "experiment_backlog": [
                    {
                        "priority": 1,
                        "experiment_id": "EXIT_SLTP_GEOMETRY",
                        "title": "Rejouer la geometrie SL/TP",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = StageResult(
        key="pnl_improvement_lab",
        title="Lab",
        status="PASSED",
        return_code=0,
        duration_seconds=0.1,
        log_path=str(output_dir / "lab.log"),
        message="ok",
        command=("python",),
    )

    markdown_path, json_path = write_reports(
        output_dir,
        root=tmp_path,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:01:00+00:00",
        mode="standard",
        inventory={},
        results=(result,),
    )

    markdown = markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "Verite PnL actuelle" in markdown
    assert "Causes PnL mesurees" in markdown
    assert "SLTP_STOP_LOSS" in markdown
    assert "Consensus >= 3" in markdown
    assert "liquidity_score incomplet" in markdown
    assert "Backlog d'experiences priorise" in markdown
    assert "EXIT_SLTP_GEOMETRY" in markdown
    assert payload["analysis"]["pnl_lab"]["automatic_activation"] is False


def test_root_launchers_keep_runtime_and_analysis_separate():
    main_launcher = (ROOT / "LANCER_HYPERSMART.cmd").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    analysis_launcher = (ROOT / "ANALYSER_BACKTESTS_REPLAYS.cmd").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    # Le runtime demarre le profil HARVEST (socle CORE allMids+BBO+userFills OBLIGATOIRE) et ne fait
    # aucune recherche dans le hot path (l'analyse reste hors runtime).
    assert "superviseur_collecteurs demarrer-tous harvest" in main_launcher
    assert "chercher_toutes" not in main_launcher
    # L'analyse est un lanceur SEPARE, atteignable depuis le runtime (sous-commande replay).
    assert 'call "%~dp0ANALYSER_BACKTESTS_REPLAYS.cmd"' in main_launcher
    # ANALYSER : MEME Python que le runtime (portable_env), porte d'entree de SESSION puis laboratoire,
    # paper strict (aucune execution reelle possible).
    assert "portable_env.cmd" in analysis_launcher
    assert "hl_observer.ops.analyser_session" in analysis_launcher
    assert "hl_observer.ops.lab_alpha" in analysis_launcher
    assert "HL_ENABLE_MAINNET_EXECUTION=0" in analysis_launcher
    assert "HL_ENABLE_TESTNET_EXECUTION=0" in analysis_launcher
    # item 10 : la porte de session (selection + verification COMPLETE) passe AVANT le laboratoire —
    # on n'analyse que des donnees COMPLETE verifiees, jamais une session ACTIVE/QUARANTINED.
    assert analysis_launcher.index("analyser_session") < analysis_launcher.index("lab_alpha")
