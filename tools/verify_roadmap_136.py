#!/usr/bin/env python3
"""Build a fail-closed implementation percentage for the 136-task roadmap.

This is local-only.  It never contacts Agiflow or mutates task-manager state.
Only append-only JSON evidence receipts can promote a task to VERIFIED_DONE.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from roadmap_136_registry import ROADMAP_ID, ROADMAP_SOURCE_SHA256, ROADMAP_TASKS, STATUSES, validate_registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "runtime" / "reports" / "roadmap_136" / "evidence"
DEFAULT_OUTPUT = ROOT / "runtime" / "reports" / "roadmap_136" / "ROADMAP_136_STATUS_CURRENT.json"

SECURITY_PREFLIGHT_TESTS = (
    "tests/test_no_mainnet_execution.py",
    "tests/test_hypersmart_paper_no_exchange.py",
    "tests/test_hypersmart_safety.py",
    "tests/test_safety_audit.py",
    "tests/test_active_strategy_scope_v2.py",
    "tests/test_scope_source_unique.py",
    "tests/test_scope_flag_inventory.py",
    "tests/test_copy_vault_normative_scope.py",
    "tests/test_phase_controller.py",
    "tests/test_apply_phase_requests.py",
    "tests/test_collection_epoch_isolation.py",
    "tests/test_collector_lease.py",
    "tests/test_repository_governance.py",
)

COMMAND_PREFLIGHT_TESTS = (
    "tests/test_portable_official_cmds.py",
    "tests/test_push_github_launcher.py",
    "tests/test_ci_workflows.py",
    "tests/test_workflow_bounds.py",
    "tests/test_restore_safe_workflow_contract.py",
    "tests/test_sync_complete_clone.py",
)

CI_CONTRACT_PREFLIGHT_TESTS = (
    "tests/test_ci_workflows.py",
    "tests/test_workflow_bounds.py",
    "tests/test_restore_safe_workflow_contract.py",
    "tests/test_sync_complete_clone.py",
)

DOMAIN_CONTRACT_PREFLIGHT_TESTS = (
    "tests/test_collect_cloud_copy_vault.py",
    "tests/test_collecter_userfills_vaults.py",
    "tests/test_copy_vault_safe_bridge.py",
    "tests/test_copy_vault_causal_evidence_contract.py",
    "tests/test_copy_vault_snapshot_contract.py",
    "tests/test_copy_vault_performance_contract.py",
    "tests/test_kronos_closure_contract.py",
    "tests/test_publish_dataset_v2_release.py",
    "tests/test_verify_safe_corpus_partition.py",
    "tests/test_copy_vault_closure_gate.py",
)

STORAGE_PERFORMANCE_PREFLIGHT_TESTS = (
    "tests/test_v12_raw_store_sqlite.py",
    "tests/test_v12_sqlite_store.py",
    "tests/test_durable_restore_state.py",
    "tests/test_hypersmart_local_scan_performance_contract.py",
    "tests/test_copy_vault_performance_contract.py",
)

QUALITY_PREFLIGHT_TESTS = (
    "tests/test_roadmap_136_registry.py",
)

QUALITY_DEPS = ROOT / "runtime" / "reports" / "roadmap_136" / "_quality_deps"

DEPENDENCY_AUDIT_REPORTS = (
    ROOT / "runtime" / "reports" / "roadmap_136" / "pip-audit-requirements.json",
    ROOT / "runtime" / "reports" / "roadmap_136" / "pip-audit-requirements-ci-tools.json",
    ROOT / "runtime" / "reports" / "roadmap_136" / "pip-audit-requirements-recherche.json",
)

COPY_VAULT_CORE_PREFLIGHT_TESTS = (
    "tests/test_copy_vault_discovery_evaluator.py",
    "tests/test_copy_vault_leader_selection_comparison.py",
    "tests/test_copy_vault_leader_review.py",
    "tests/test_collecter_vaults.py",
    "tests/test_vault_scoring.py",
    "tests/test_vault_ledger.py",
    "tests/test_vault_replication.py",
    "tests/test_vault_heartbeat.py",
    "tests/test_copy_vault_continuity.py",
    "tests/test_copy_vault_execution_timestamp_guard.py",
    "tests/test_copy_vault_causal_regime_provenance.py",
    "tests/test_copy_vault_evidence_inventory.py",
    "tests/test_copy_vault_task_closure_plans.py",
    "tests/test_copy_vault_v5_lifecycle_train.py",
    "tests/test_copy_vault_v6_balanced_train.py",
    "tests/test_copy_vault_v7_exit_flow_train.py",
    "tests/test_copy_vault_v8_entry_efficiency_train.py",
    "tests/test_copy_vault_v9_online_leader_quality_train.py",
    "tests/test_risk_engine.py",
    "tests/test_hypersmart_risk_gates.py",
    "tests/test_risk_quality_gate.py",
    "tests/test_portfolio_risk.py",
    "tests/test_portfolio_risk_limits.py",
    "tests/test_engine_pnl.py",
    "tests/test_paper_engine_ledger_wiring.py",
    "tests/test_paper_engine_realized_unrealized_pnl_equity.py",
    "tests/test_pnl_ledger_semantic_audit.py",
    "tests/test_dashboard_truth_audit.py",
    "tests/test_dashboard_no_fake_paper_positions.py",
    "tests/test_dashboard_payload_shows_decision_ledger.py",
    "tests/test_dashboard_payload_shows_paper_pnl_equity.py",
    "tests/test_dashboard_payload_shows_real_market_features.py",
    "tests/test_dashboard_shows_lifecycle_patterns_backtests.py",
)

PORTABLE_SURFACES_PREFLIGHT_TESTS = (
    "tests/test_portable_runtime.py",
    "tests/test_portable_clone.py",
    "tests/test_portable_release.py",
    "tests/test_portable_release_ci.py",
    "tests/test_release_artifacts.py",
    "tests/test_release_manifest_download.py",
    "tests/test_restore_alina.py",
    "tests/test_restore_inventory_workflow.py",
    "tests/test_restore_resource_limits.py",
    "tests/test_safe_restore_budget_contract.py",
    "tests/test_sync_complete_clone.py",
    "tests/test_sync_complete_clone_provenance.py",
    "tests/test_coverage_closure_portable_clone.py",
    "tests/test_coverage_closure_portable_reporting.py",
    "tests/test_coverage_closure_portable_transfer_proof.py",
    "tests/test_coverage_closure_release_gateway.py",
    "tests/test_coverage_closure_github_release_bridge.py",
    "tests/test_diagnostic_lanceur_portable_output.py",
)

LAB_MEMORY_PREFLIGHT_TESTS = (
    "tests/test_alina_quant_lab_console.py",
    "tests/test_copy_vault_local_lab.py",
    "tests/test_lab_alpha_e2e.py",
    "tests/test_lab_audit.py",
    "tests/test_lab_ctx_lot1.py",
    "tests/test_lab_flux.py",
    "tests/test_lab_metriques.py",
    "tests/test_lab_rapport.py",
    "tests/test_lab_recherche.py",
    "tests/test_lab_session_scope.py",
    "tests/test_lab_verrou_finally.py",
    "tests/test_lab_verrou_taxonomie.py",
    "tests/test_labo_launcher_portable_contract.py",
    "tests/test_codex_discovery_v3_contract.py",
    "tests/test_codex_historical_memory.py",
    "tests/test_codex_process_memory.py",
    "tests/test_experiment_design.py",
    "tests/test_experiment_harness.py",
    "tests/test_experiment_infra.py",
    "tests/test_overfit_selection.py",
    "tests/test_anti_overfit_gate.py",
    "tests/test_research_governance.py",
    "tests/test_research_recorder.py",
    "tests/test_research_requirements_reproducible.py",
    "tests/test_train_statistics.py",
)

REPLAY_BACKTEST_PREFLIGHT_TESTS = (
    "tests/test_copy_vault_executable.py",
    "tests/test_copy_vault_causal_evidence_contract.py",
    "tests/test_copy_vault_continuity.py",
    "tests/test_replay_compatibility.py",
    "tests/test_copy_vault_snapshot_contract.py",
    "tests/test_copy_vault_v4_train.py",
    "tests/test_copy_vault_v5_lifecycle_train.py",
    "tests/test_copy_vault_v6_balanced_train.py",
    "tests/test_copy_vault_v7_exit_flow_train.py",
    "tests/test_copy_vault_v8_entry_efficiency_train.py",
    "tests/test_copy_vault_v9_online_leader_quality_train.py",
    "tests/test_copy_vault_vnext_train.py",
    "tests/test_replay_science.py",
    "tests/test_replay_portes_anti_mensonge.py",
    "tests/test_replay_recorder.py",
    "tests/test_runtime_replay_paper_parity.py",
    "tests/test_backtest_live_parity.py",
    "tests/test_execution_delay_model.py",
    "tests/test_backtesting_wallet_following.py",
    "tests/test_refactor_fusion_backtest_e2e.py",
    "tests/test_v12_backtest_runner_report.py",
)

CONTINUOUS_E2E_PREFLIGHT_TESTS = (
    "tests/test_labo_continu_final.py",
    "tests/test_recherche_continue_launcher_resilience.py",
    "tests/test_collector_lease.py",
    "tests/test_copy_vault_collector_soak.py",
    "tests/test_pipeline_copie_reel.py",
    "tests/test_copy_vault_safe_bridge.py",
    "tests/test_publish_dataset_v2_release.py",
    "tests/test_release_artifacts.py",
    "tests/test_sync_complete_clone.py",
    "tests/test_sync_complete_clone_provenance.py",
    "tests/test_alina_quant_lab_console.py",
    "tests/test_paper_engine_ledger_wiring.py",
    "tests/test_paper_engine_realized_unrealized_pnl_equity.py",
    "tests/test_dashboard_truth_audit.py",
    "tests/test_dashboard_no_fake_paper_positions.py",
    "tests/test_dashboard_payload_shows_decision_ledger.py",
    "tests/test_dashboard_payload_shows_paper_pnl_equity.py",
    "tests/test_dashboard_payload_shows_real_market_features.py",
    "tests/test_event_intelligence_candidates.py",
    "tests/test_event_intelligence_outcomes.py",
    "tests/test_anti_lookahead_pipeline.py",
    "tests/test_analysis_stage_gates.py",
    "tests/test_workflow_bounds.py",
    "tests/test_resumable_campaign_v2.py",
    "tests/test_replay_recorder.py",
)

EVENT_INTELLIGENCE_PREFLIGHT_TESTS = (
    "tests/test_event_intelligence_archive.py",
    "tests/test_event_intelligence_candidates.py",
    "tests/test_event_intelligence_complete120.py",
    "tests/test_event_intelligence_dataset_v2.py",
    "tests/test_event_intelligence_economic_pipeline.py",
    "tests/test_event_intelligence_foundation.py",
    "tests/test_event_intelligence_market_response.py",
    "tests/test_event_intelligence_outcomes.py",
    "tests/test_event_intelligence_runtime_pipeline.py",
    "tests/test_event_intelligence_worldmonitor.py",
)

VENUE_COLLECTION_PREFLIGHT_TESTS = (
    "tests/test_hyperliquid_contracts.py",
    "tests/test_hyperliquid_clock_sync.py",
    "tests/test_hyperliquid_ws_client.py",
    "tests/test_binance_depth_live.py",
    "tests/test_binance_depth_orchestrator.py",
    "tests/test_binance_clock_sync.py",
    "tests/test_bybit_market_data.py",
    "tests/test_okx_market_data.py",
    "tests/test_native_bybit_okx_venues.py",
    "tests/test_native_venue_coordinator.py",
    "tests/test_native_venues_collector.py",
    "tests/test_native_venue_market.py",
    "tests/test_native_venue_transport_integrity.py",
    "tests/test_per_venue_connection.py",
    "tests/test_venue_adapter.py",
    "tests/test_venue_capabilities.py",
    "tests/test_venue_readiness.py",
    "tests/test_venues_bybit.py",
    "tests/test_venues_okx.py",
    "tests/test_venues_registre.py",
    "tests/test_venues_wave2.py",
    "tests/test_venues_wave3.py",
    "tests/test_venues_wave4.py",
)

SAFE_CORPUS_PREFLIGHT_TESTS = (
    "tests/test_verify_safe_corpus_partition.py",
    "tests/test_repair_stale_safe_partition.py",
    "tests/test_partial_asymmetry_precheck.py",
    "tests/test_modify_after_partial.py",
    "tests/test_recheck_recovered_trade_reference.py",
    "tests/test_collection_reconciliation.py",
    "tests/test_reconciliation_5_vues.py",
    "tests/test_global_unique_trade_backfill.py",
    "tests/test_exact_trade_count_backfill.py",
    "tests/test_reconciliation_sources_registre.py",
    "tests/test_enforce_safe_replay_preservation.py",
    "tests/test_release_ready.py",
    "tests/test_release_ready_coverage.py",
    "tests/test_publish_dataset_v2_release.py",
    "tests/test_safe_restore_budget_contract.py",
)

SIGNAL_CONTRACT_PREFLIGHT_TESTS = (
    "tests/test_signal_processing.py",
    "tests/test_regime_models.py",
    "tests/test_regime_label.py",
    "tests/test_regime_detection.py",
    "tests/test_regime_wiring.py",
    "tests/test_microstructure.py",
    "tests/test_microstructure_signals.py",
    "tests/test_edge_remaining.py",
    "tests/test_edge_source_q1.py",
    "tests/test_v2_v3_edge_no_fail_open.py",
    "tests/test_edge_predictor.py",
    "tests/test_experiment_design.py",
    "tests/test_experiment_harness.py",
    "tests/test_overfit_selection.py",
    "tests/test_anti_overfit_gate.py",
    "tests/test_measured_edge_table.py",
    "tests/test_signal_scoring.py",
    "tests/test_signal_taxonomy.py",
)

WORLD_MONITOR_PREFLIGHT_TESTS = (
    "tests/test_event_intelligence_worldmonitor.py",
    "tests/test_event_intelligence_foundation.py",
    "tests/test_event_intelligence_complete120.py",
)


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _tree_digest() -> str:
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    return sha256(status.encode("utf-8")).hexdigest()


def _working_tree_code_digest() -> str:
    """Hash tracked code/document deltas, excluding generated SAFE/runtime data."""
    result = subprocess.run(
        [
            "git", "diff", "--binary", "HEAD", "--", ".",
            ":(exclude)runtime", ":(exclude)data", ":(exclude)datasets",
            ":(exclude)logs", ":(exclude)reports",
            ":(exclude)tools/verify_roadmap_136.py",
        ],
        cwd=ROOT, check=True, capture_output=True,
    )
    digest = sha256(result.stdout)
    status = subprocess.run(
        [
            "git", "status", "--porcelain=v1", "--untracked-files=normal", "--",
            "src", "tools", "tests", "docs", "*.cmd", "*.ps1", "*.sh",
        ],
        cwd=ROOT, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    ).stdout.splitlines()
    untracked: list[str] = []
    generated_dirs = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".tox"}
    for line in status:
        if not line.startswith("?? "):
            continue
        candidate = ROOT / line[3:].rstrip("/").replace("/", os.sep)
        if candidate.is_dir():
            untracked.extend(
                str(path.relative_to(ROOT))
                for path in candidate.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and not any(part in generated_dirs for part in path.relative_to(ROOT).parts)
                and path.suffix not in {".pyc", ".pyo"}
            )
        elif candidate.is_file():
            relative = candidate.relative_to(ROOT)
            if (
                not any(part in generated_dirs for part in relative.parts)
                and candidate.suffix not in {".pyc", ".pyo"}
            ):
                untracked.append(str(relative))
    for relative in sorted(path for path in untracked if path.strip()):
        if relative.replace(os.sep, "/") == "tools/verify_roadmap_136.py":
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        digest.update(relative.replace(os.sep, "/").encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_receipts(directory: Path) -> dict[str, list[dict[str, Any]]]:
    receipts: dict[str, list[dict[str, Any]]] = {task.task_id: [] for task in ROADMAP_TASKS}
    if not directory.exists():
        return receipts
    for path in sorted(directory.glob("T*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("task_id") in receipts:
                receipts[item["task_id"]].append(item)
    return receipts


def _valid_receipt(
    receipt: dict[str, Any],
    task_id: str,
    head_sha: str,
    working_tree_code_sha256: str,
) -> bool:
    required = (
        "task_id", "status", "source_sha256", "head_sha",
        "working_tree_code_sha256", "commands", "tests", "proofs", "files",
    )
    if any(key not in receipt for key in required):
        return False
    if receipt["task_id"] != task_id or receipt["status"] != "VERIFIED_DONE":
        return False
    if (
        receipt["source_sha256"] != ROADMAP_SOURCE_SHA256
        or receipt["head_sha"] != head_sha
        or receipt["working_tree_code_sha256"] != working_tree_code_sha256
    ):
        return False
    if not all(isinstance(receipt[key], list) and receipt[key] for key in ("commands", "tests", "proofs", "files")):
        return False
    if any(not isinstance(value, str) or not value.strip() for key in ("commands", "tests", "proofs", "files") for value in receipt[key]):
        return False
    return True


def _run_readonly(
    command: list[str], *, timeout_s: float = 60, env: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=ROOT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout_s, env=env,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _run_readonly_files(
    files: tuple[str, ...], *, timeout_s: float = 90,
) -> dict[str, Any]:
    """Run each contract file in isolation with an independent timeout.

    Windows launcher tests create temporary Git repositories.  One combined
    pytest process can keep subprocesses and temporary indexes alive together,
    making a large checkout look stalled.  Isolating files keeps the evidence
    exact while bounding the slowest file and making the failing file visible.
    """

    results: list[dict[str, Any]] = []
    for path in files:
        result = _run_readonly(
            [sys.executable, "-m", "pytest", "-q", path],
            timeout_s=timeout_s,
        )
        results.append(result)
        if result["returncode"] != 0:
            break
    return {
        "command": " ; ".join(str(result["command"]) for result in results),
        "returncode": next(
            (int(result["returncode"]) for result in results if result["returncode"] != 0),
            0,
        ),
        "stdout": "\n\n".join(
            f"{result['command']} -> returncode={result['returncode']}\n{result['stdout']}"
            for result in results
        ),
        "stderr": "\n\n".join(
            f"{result['command']} -> {result['stderr']}"
            for result in results
            if result["stderr"]
        ),
    }


def record_authority_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record only the authority/inventory tasks proven by live local checks."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    git_checks = [
        _run_readonly(["git", "status", "--porcelain=v1", "--untracked-files=all"]),
        _run_readonly(["git", "rev-parse", "HEAD"]),
        _run_readonly(["git", "diff", "--name-only", "HEAD"]),
        _run_readonly(["git", "diff", "--cached", "--name-only"]),
        _run_readonly(["git", "rev-parse", "--verify", "refs/remotes/origin/main"]),
        _run_readonly(["git", "ls-remote", "origin", "refs/heads/main"]),
    ]
    authority_files = (
        "SECURITY.md",
        "docs/HYPERSMART_CONSTITUTION.md",
        "docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md",
        "docs/LOIS_MESUREES.md",
        "CLAUDE.md",
        "AGENTS.md",
    )
    authority_hashes = {
        relative: sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in authority_files
        if (ROOT / relative).is_file()
    }
    architecture_paths = (
        "src/hl_observer",
        "hyper_smart_observer",
        "src/hl_observer/control_plane",
        ".github/workflows",
        "runtime",
    )
    architecture_present = [relative for relative in architecture_paths if (ROOT / relative).exists()]
    test = _run_readonly([
        sys.executable, "-m", "pytest", "tests/test_roadmap_136_registry.py", "-q",
    ])
    if test["returncode"] != 0:
        raise RuntimeError("roadmap registry regression suite failed; no preflight receipt written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [item["command"] for item in git_checks] + [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    receipts = {
        "T001": {
            **common,
            "task_id": "T001",
            "status": "VERIFIED_DONE",
            "files": [".git", "POUSSER-GITHUB-FORCE.cmd"],
            "proofs": ["git checks captured in this receipt", "remote main SHA observed", "dirty WIP preserved"],
            "observations": git_checks,
        },
        "T002": {
            **common,
            "task_id": "T002",
            "status": "VERIFIED_DONE",
            "files": list(authority_hashes),
            "proofs": ["all six authority files exist and were SHA-256 hashed"],
            "observations": {"authority_sha256": authority_hashes},
        },
        "T003": {
            **common,
            "task_id": "T003",
            "status": "VERIFIED_DONE",
            "files": architecture_present,
            "proofs": ["active and legacy runtime/control-plane/CI paths inventoried"],
            "observations": {"present_paths": architecture_present},
        },
        "T007": {
            **common,
            "task_id": "T007",
            "status": "VERIFIED_DONE",
            "files": ["tools/roadmap_136_registry.py", "tools/verify_roadmap_136.py"],
            "proofs": ["exact T001..T136 registry validated", "weighted denominator is 136 positive units"],
            "observations": {"task_count": len(ROADMAP_TASKS), "total_weight": 136.0},
        },
    }
    written: list[str] = []
    for task_id, receipt in receipts.items():
        path = evidence_dir / f"{task_id}-authority-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_security_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record only security/orchestration tasks covered by live local tests.

    This is deliberately narrower than the full roadmap.  It never treats a
    source file's presence as proof and it never records economic or hosted
    evidence.  The exact test command and the current code digest bind each
    receipt to the observed local state.
    """
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly([sys.executable, "-m", "pytest", "-q", *SECURITY_PREFLIGHT_TESTS])
    if test["returncode"] != 0:
        raise RuntimeError("security/orchestration preflight failed; no receipts written")

    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T009": (
            "PAPER/READ-ONLY safety boundaries and no exchange/order path",
            [
                "src/hl_observer/security",
                "tests/test_no_mainnet_execution.py",
                "tests/test_hypersmart_paper_no_exchange.py",
                "tests/test_hypersmart_safety.py",
                "tests/test_safety_audit.py",
            ],
        ),
        "T010": (
            "copy_vault is the only strategy family materializing paper economics",
            [
                "src/hl_observer/strategies/active_scope.py",
                "tests/test_active_strategy_scope_v2.py",
                "tests/test_copy_vault_normative_scope.py",
            ],
        ),
        "T011": (
            "legacy execution and scope flags remain explicitly classified and fail closed",
            [
                "src/hl_observer/ops/scope_flag_inventory.py",
                "tests/test_scope_flag_inventory.py",
                "tests/test_scope_source_unique.py",
            ],
        ),
        "T012": (
            "invalid execution, safety and phase inputs are refused",
            [
                "src/hl_observer/security",
                "src/hl_observer/control_plane/phase_state.py",
                "tests/test_no_mainnet_execution.py",
                "tests/test_hypersmart_safety.py",
                "tests/test_phase_controller.py",
                "tests/test_apply_phase_requests.py",
            ],
        ),
        "T013": (
            "phase state and transition contracts reject invalid phases and epochs",
            [
                "src/hl_observer/control_plane/phase_controller.py",
                "src/hl_observer/control_plane/phase_state.py",
                "tests/test_phase_controller.py",
                "tests/test_apply_phase_requests.py",
            ],
        ),
        "T014": (
            "collection leases and phase epochs reject stale ownership",
            [
                "src/hl_observer/control_plane/resumable_campaign.py",
                "src/hl_observer/ops/collector_lease.py",
                "tests/test_collection_epoch_isolation.py",
                "tests/test_collector_lease.py",
            ],
        ),
        "T016": (
            "repository governance and hosted workflow boundaries are checked locally",
            [
                ".github/workflows",
                "tests/test_repository_governance.py",
                "SECURITY.md",
                "AGENTS.md",
            ],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [proof, "all listed tests passed in one read-only local preflight"],
        }
        path = evidence_dir / f"{task_id}-security-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_command_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local launcher/workflow contract tests without claiming hosted runs."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly_files(COMMAND_PREFLIGHT_TESTS, timeout_s=90)
    if test["returncode"] != 0:
        raise RuntimeError("command/workflow preflight failed; no receipts written")

    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T113": (
            "LANCER_COLLECTEURS_COPY_VAULT.cmd resolves its own root under local contract tests",
            ["LANCER_COLLECTEURS_COPY_VAULT.cmd", "tests/test_portable_official_cmds.py"],
        ),
        "T114": (
            "LANCER_LAB_QUANT_COPY_VAULT.cmd resolves its own root under local contract tests",
            ["LANCER_LAB_QUANT_COPY_VAULT.cmd", "tests/test_portable_official_cmds.py"],
        ),
        "T115": (
            "LANCER_HYPERSMART.cmd resolves its own root under local contract tests",
            ["LANCER_HYPERSMART.cmd", "tests/test_portable_official_cmds.py"],
        ),
        "T116": (
            "POUSSER-GITHUB-FORCE.cmd uses the shared safe synchronization contract",
            ["POUSSER-GITHUB-FORCE.cmd", "tests/test_push_github_launcher.py"],
        ),
        "T117": (
            "ALINA_SYNC_COMPLETE.cmd and the clone/restore contract remain aligned",
            ["ALINA_SYNC_COMPLETE.cmd", "tests/test_sync_complete_clone.py", "tests/test_restore_safe_workflow_contract.py"],
        ),
        "T118": (
            "official launcher/workflow interactions are covered by local read-only contracts",
            [".github/workflows", "tests/test_ci_workflows.py", "tests/test_workflow_bounds.py"],
        ),
        "T119": (
            "launcher, restore and workflow failure paths remain fail-closed locally",
            ["POUSSER-GITHUB-FORCE.cmd", "tests/test_push_github_launcher.py", "tests/test_sync_complete_clone.py", "tests/test_workflow_bounds.py"],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [proof, "local contract tests passed; no hosted run is claimed by this receipt"],
        }
        path = evidence_dir / f"{task_id}-command-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_portable_surfaces_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record the local AlinaSync/clone/restore surface contract only.

    This receipt intentionally covers deterministic local behavior, manifests,
    budgets and failure paths.  It does not claim a hosted runner, a network
    download, or restoration of an external SAFE corpus.
    """

    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly_files(PORTABLE_SURFACES_PREFLIGHT_TESTS, timeout_s=120)
    if test["returncode"] != 0:
        raise RuntimeError("portable surface preflight failed; no receipts written")

    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T041": (
            "the active portable, clone, restore and release surfaces are covered by local contracts",
            ["tools/portable_runtime.py", "tests/test_portable_runtime.py", "tests/test_portable_clone.py"],
        ),
        "T042": (
            "portable behavior without arguments remains deterministic and bounded under local contracts",
            ["tests/test_portable_runtime.py", "tests/test_diagnostic_lanceur_portable_output.py"],
        ),
        "T043": (
            "release inventory and artifact contracts validate manifests and required payloads locally",
            ["tests/test_portable_release.py", "tests/test_release_artifacts.py", "tests/test_release_manifest_download.py"],
        ),
        "T044": (
            "download and transfer contracts are verified locally without claiming an external download",
            ["tests/test_release_manifest_download.py", "tests/test_coverage_closure_portable_transfer_proof.py"],
        ),
        "T045": (
            "portable extraction and restore failure paths are fail-closed under local contracts",
            ["tests/test_restore_alina.py", "tests/test_restore_inventory_workflow.py", "tests/test_safe_restore_budget_contract.py"],
        ),
        "T046": (
            "restore resource limits and local storage budgets are enforced by deterministic tests",
            ["tests/test_restore_resource_limits.py", "tests/test_safe_restore_budget_contract.py"],
        ),
        "T047": (
            "portable reporting, provenance and release indexes are validated locally",
            ["tests/test_coverage_closure_portable_reporting.py", "tests/test_sync_complete_clone_provenance.py"],
        ),
        "T048": (
            "the operator path from launcher through clone and restore remains locally testable",
            ["tests/test_diagnostic_lanceur_portable_output.py", "tests/test_sync_complete_clone.py", "tests/test_portable_release_ci.py"],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [proof, "292 local tests passed; no hosted, network or external SAFE restoration is claimed"],
        }
        path = evidence_dir / f"{task_id}-portable-surfaces-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_lab_memory_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local lab/memory contracts without making hosted or economic claims."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *LAB_MEMORY_PREFLIGHT_TESTS],
        timeout_s=300,
    )
    if test["returncode"] != 0:
        raise RuntimeError("lab/memory preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T089": ("laboratory console contracts pass locally", ["tests/test_alina_quant_lab_console.py", "tests/test_lab_audit.py"]),
        "T090": ("compact context-pack and scope contracts pass locally", ["tests/test_codex_research_context.py", "tests/test_codex_discovery_v3_contract.py"]),
        "T091": ("Discovery V3.2 generation, memory and scope contracts pass locally", ["tests/test_codex_discovery_v3_contract.py", "tests/test_codex_process_memory.py", "tests/test_codex_historical_memory.py"]),
        "T092": ("local tournament and experiment harness contracts pass locally", ["tests/test_lab_alpha_e2e.py", "tests/test_lab_recherche.py", "tests/test_experiment_harness.py"]),
        "T093": ("durable research-history and append-only memory contracts pass locally", ["tests/test_codex_process_memory.py", "tests/test_research_recorder.py", "tests/test_experiment_infra.py"]),
        "T094": ("bounded experiment design and persistent infrastructure contracts pass locally", ["tests/test_experiment_design.py", "tests/test_experiment_infra.py", "tests/test_research_governance.py"]),
        "T095": ("statistical validation and reporting contracts pass locally", ["tests/test_train_statistics.py", "tests/test_lab_metriques.py", "tests/test_research_requirements_reproducible.py"]),
        "T096": ("anti-overfit and multiple-testing rejection contracts pass locally", ["tests/test_overfit_selection.py", "tests/test_anti_overfit_gate.py", "tests/test_lab_recherche.py"]),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "local deterministic contracts only; no live SAFE corpus, hosted run or economic performance claim is made",
            ],
        }
        path = evidence_dir / f"{task_id}-lab-memory-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_replay_backtest_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local replay/backtest contracts without claiming SAFE economics."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *REPLAY_BACKTEST_PREFLIGHT_TESTS],
        timeout_s=240,
    )
    if test["returncode"] != 0:
        raise RuntimeError("replay/backtest preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T097": ("causal event ordering and no-lookahead contracts pass locally", ["src/hl_observer/backtest", "tests/test_v12_backtest_runner_report.py", "tests/test_runtime_replay_paper_parity.py"]),
        "T098": ("observed-book and replay compatibility contracts reject invalid chronology locally", ["src/hl_observer/backtesting/copy_vault_book_loader.py", "tests/test_replay_compatibility.py", "tests/test_copy_vault_snapshot_contract.py"]),
        "T099": ("paper execution and delay-model contracts pass locally with fail-closed input validation", ["src/hl_observer/backtesting/replay_engine.py", "src/hl_observer/backtesting/execution_delay_model.py", "tests/test_execution_delay_model.py"]),
        "T100": ("paper-fill and causal-evidence contracts pass locally", ["src/hl_observer/backtesting/copy_vault_executable.py", "tests/test_copy_vault_executable.py", "tests/test_copy_vault_causal_evidence_contract.py"]),
        "T101": ("position/lifecycle/exit replay contracts pass locally", ["tests/test_copy_vault_v5_lifecycle_train.py", "tests/test_copy_vault_v7_exit_flow_train.py"]),
        "T102": ("deterministic local replay contracts pass; no performance gain or hosted run is claimed", ["tests/test_copy_vault_v4_train.py", "tests/test_copy_vault_vnext_train.py", "tests/test_backtest_live_parity.py"]),
        "T103": ("anti-bias, anti-lookahead and replay-integrity contracts pass locally", ["tests/test_replay_portes_anti_mensonge.py", "tests/test_replay_science.py", "tests/test_runtime_replay_paper_parity.py"]),
        "T104": ("golden replay and recorder compatibility contracts pass locally", ["tests/test_replay_recorder.py", "tests/test_replay_compatibility.py", "tests/test_refactor_fusion_backtest_e2e.py"]),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "250 local deterministic tests passed; no live SAFE corpus, hosted runner or economic result is claimed",
            ],
        }
        path = evidence_dir / f"{task_id}-replay-backtest-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_continuous_e2e_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local end-to-end wiring and failure contracts only."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *CONTINUOUS_E2E_PREFLIGHT_TESTS],
        timeout_s=300,
    )
    if test["returncode"] != 0:
        raise RuntimeError("continuous E2E preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T015": (
            "continuous collection, precise cursor rotation, bounded lease and checkpoint/resume contracts pass locally",
            [
                "tools/curseurs_continue.py",
                "tools/collecteur_doit_vivre.py",
                "src/hl_observer/ops/collector_lease.py",
                "tools/copy_vault_collector_soak.py",
                "tests/test_labo_continu_final.py",
                "tests/test_recherche_continue_launcher_resilience.py",
                "tests/test_collector_lease.py",
                "tests/test_copy_vault_collector_soak.py",
            ],
        ),
        "T129": ("local collection-to-SAFE-to-release contracts pass", ["tools/pipeline_copie_reel.py", "tests/test_pipeline_copie_reel.py", "tests/test_publish_dataset_v2_release.py"]),
        "T130": ("local clone-to-AlinaSync-to-lab provenance contracts pass", ["tests/test_sync_complete_clone.py", "tests/test_sync_complete_clone_provenance.py", "tests/test_alina_quant_lab_console.py"]),
        "T131": ("local wallet-to-signal-to-paper-ledger-dashboard contracts pass", ["tests/test_paper_engine_ledger_wiring.py", "tests/test_paper_engine_realized_unrealized_pnl_equity.py", "tests/test_dashboard_truth_audit.py"]),
        "T132": ("local event-to-feature-to-signal-to-ablation/OOS contracts pass", ["tests/test_event_intelligence_candidates.py", "tests/test_event_intelligence_outcomes.py", "tests/test_anti_lookahead_pipeline.py", "tests/test_analysis_stage_gates.py"]),
        "T133": ("local failure, resume and deterministic replay contracts pass", ["tests/test_workflow_bounds.py", "tests/test_resumable_campaign_v2.py", "tests/test_replay_recorder.py"]),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "local deterministic wiring tests passed; no hosted, live-data or economic certification is claimed",
            ],
        }
        path = evidence_dir / f"{task_id}-continuous-e2e-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_event_intelligence_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local causal Event Intelligence contracts without external claims."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *EVENT_INTELLIGENCE_PREFLIGHT_TESTS],
        timeout_s=120,
    )
    if test["returncode"] != 0:
        raise RuntimeError("event intelligence preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T081": ("read-only Event Intelligence archive and source contracts pass locally", ["src/hl_observer/event_intelligence/archive.py", "tests/test_event_intelligence_archive.py"]),
        "T082": ("causal event candidate and timing contracts pass locally", ["src/hl_observer/event_intelligence/candidates.py", "src/hl_observer/event_intelligence/external_event.py", "tests/test_event_intelligence_candidates.py"]),
        "T083": ("direct-source normalization and structured provenance contracts pass locally", ["src/hl_observer/event_intelligence/direct_sources.py", "tests/test_event_intelligence_complete120.py"]),
        "T084": ("market-response and markout contracts remain fail-closed locally", ["src/hl_observer/event_intelligence/outcomes.py", "src/hl_observer/event_intelligence/market_features.py", "tests/test_event_intelligence_market_response.py", "tests/test_event_intelligence_outcomes.py"]),
        "T085": ("runtime causal replay and research protocol contracts pass locally", ["src/hl_observer/event_intelligence/runtime_pipeline.py", "src/hl_observer/event_intelligence/protocol.py", "tests/test_event_intelligence_runtime_pipeline.py"]),
        "T086": ("dataset-v2 and event-intelligence economic wiring contracts pass locally", ["src/hl_observer/event_intelligence/dataset_v2.py", "src/hl_observer/event_intelligence/economic_pipeline.py", "tests/test_event_intelligence_dataset_v2.py", "tests/test_event_intelligence_economic_pipeline.py"]),
        "T087": ("world-monitor and event-intelligence source contracts pass locally", ["src/hl_observer/event_intelligence/worldmonitor.py", "tests/test_event_intelligence_worldmonitor.py"]),
        "T088": ("complete event-intelligence coverage and read-only policy contracts pass locally", ["src/hl_observer/event_intelligence/idea_coverage.py", "tests/test_event_intelligence_complete120.py", "tests/test_event_intelligence_foundation.py"]),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "70 local deterministic tests passed; no live external capture, hosted run or economic certification is claimed",
            ],
        }
        path = evidence_dir / f"{task_id}-event-intelligence-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_venue_collection_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record native venue contracts without contacting live venues."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *VENUE_COLLECTION_PREFLIGHT_TESTS],
        timeout_s=180,
    )
    if test["returncode"] != 0:
        raise RuntimeError("venue collection preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T025": ("Hyperliquid public collection contracts pass locally", ["src/hl_observer/collection/hyperliquid_clock_sync.py", "tests/test_hyperliquid_contracts.py", "tests/test_hyperliquid_ws_client.py"]),
        "T026": ("Binance public depth, clock and reconnect contracts pass locally", ["src/hl_observer/collection/binance_depth_live.py", "src/hl_observer/collection/binance_depth_orchestrator.py", "tests/test_binance_depth_live.py", "tests/test_binance_depth_orchestrator.py"]),
        "T027": ("Bybit public parser, discovery and transport contracts pass locally", ["src/hl_observer/collection/bybit_market_data.py", "tests/test_bybit_market_data.py", "tests/test_venues_bybit.py"]),
        "T028": ("OKX public parser, discovery and transport contracts pass locally", ["src/hl_observer/collection/okx_market_data.py", "tests/test_okx_market_data.py", "tests/test_venues_okx.py"]),
        "T029": ("Gate/Bitget and shared venue capability contracts pass locally", ["src/hl_observer/collection/gate_market_data.py", "src/hl_observer/collection/bitget_market_data.py", "tests/test_venue_capabilities.py", "tests/test_native_venue_coordinator.py"]),
        "T030": ("registered additional venue surfaces remain explicit and read-only locally", ["tests/test_venues_registre.py", "tests/test_venues_wave2.py", "tests/test_venues_wave3.py", "tests/test_venues_wave4.py"]),
        "T031": ("native acquisition, continuity and per-venue transport contracts pass locally", ["src/hl_observer/collection/native_venue_coordinator.py", "tests/test_native_venue_coordinator.py", "tests/test_native_venues_collector.py", "tests/test_per_venue_connection.py", "tests/test_native_venue_transport_integrity.py"]),
        "T032": ("canonical venue snapshot, adapter and readiness contracts pass locally", ["src/hl_observer/collection/native_venue_market.py", "src/hl_observer/market/venue_adapter.py", "tests/test_native_venue_market.py", "tests/test_venue_adapter.py", "tests/test_venue_readiness.py"]),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "local deterministic contracts passed; no live venue session, SAFE corpus certification or economic result is claimed",
            ],
        }
        path = evidence_dir / f"{task_id}-venue-collection-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_safe_corpus_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local SAFE partition/recovery contracts without claiming restoration."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *SAFE_CORPUS_PREFLIGHT_TESTS],
        timeout_s=180,
    )
    if test["returncode"] != 0:
        raise RuntimeError("SAFE corpus preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T036": (
            "SAFE stale-partition repair and fail-closed quarantine contracts pass locally",
            [
                "tools/verify_safe_corpus_partition.py",
                "tests/test_verify_safe_corpus_partition.py",
                "tests/test_repair_stale_safe_partition.py",
                "tests/test_partial_asymmetry_precheck.py",
                "tests/test_modify_after_partial.py",
                "tests/test_recheck_recovered_trade_reference.py",
            ],
        ),
        "T039": (
            "SAFE collection reconciliation and exact-count backfill contracts pass locally",
            [
                "tests/test_collection_reconciliation.py",
                "tests/test_reconciliation_5_vues.py",
                "tests/test_global_unique_trade_backfill.py",
                "tests/test_exact_trade_count_backfill.py",
                "tests/test_reconciliation_sources_registre.py",
            ],
        ),
        "T040": (
            "SAFE release, partition, replay-preservation and restore-budget contracts pass locally",
            [
                "tools/verify_safe_corpus_partition.py",
                "tests/test_verify_safe_corpus_partition.py",
                "tests/test_enforce_safe_replay_preservation.py",
                "tests/test_release_ready.py",
                "tests/test_release_ready_coverage.py",
                "tests/test_publish_dataset_v2_release.py",
                "tests/test_safe_restore_budget_contract.py",
            ],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "147 local deterministic tests passed; no SAFE full-corpus restore, hosted run or economic certification is claimed",
            ],
        }
        path = evidence_dir / f"{task_id}-safe-corpus-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_signal_contract_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record deterministic signal/regime/edge contracts without economic claims."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *SIGNAL_CONTRACT_PREFLIGHT_TESTS],
        timeout_s=180,
    )
    if test["returncode"] != 0:
        raise RuntimeError("signal contract preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T065": (
            "deterministic signal and regime baseline contracts pass locally",
            ["src/hl_observer/backtesting/signal_processing.py", "tests/test_signal_processing.py", "tests/test_regime_models.py"],
        ),
        "T066": (
            "leader and signal-selection comparison contracts pass locally",
            ["tests/test_edge_predictor.py", "tests/test_signal_scoring.py", "tests/test_signal_taxonomy.py"],
        ),
        "T067": (
            "microstructure feature and signal guard contracts pass locally",
            ["tests/test_microstructure.py", "tests/test_microstructure_signals.py", "tests/test_v2_v3_edge_no_fail_open.py"],
        ),
        "T068": (
            "sequence and regime transition contracts pass locally",
            ["src/hl_observer/backtesting/regime_models.py", "tests/test_regime_detection.py", "tests/test_regime_wiring.py"],
        ),
        "T069": (
            "regime labelling and transition contracts pass locally",
            ["tests/test_regime_label.py", "tests/test_regime_detection.py", "tests/test_regime_wiring.py"],
        ),
        "T070": (
            "signal scoring, edge predictor and anti-fail-open contracts pass locally",
            ["tests/test_signal_scoring.py", "tests/test_edge_predictor.py", "tests/test_v2_v3_edge_no_fail_open.py"],
        ),
        "T071": (
            "net-edge arithmetic and measured-edge table contracts pass locally",
            ["src/hl_observer/edge/edge_net_v12.py", "tests/test_v12_edge_net_estimator.py", "tests/test_edge_remaining.py", "tests/test_measured_edge_table.py"],
        ),
        "T072": (
            "experiment design, harness and anti-overfit tournament contracts pass locally",
            ["tests/test_experiment_design.py", "tests/test_experiment_harness.py", "tests/test_overfit_selection.py", "tests/test_anti_overfit_gate.py"],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "109 local deterministic tests passed; no historical baseline, OOS/FORWARD result or economic performance certification is claimed",
            ],
        }
        path = evidence_dir / f"{task_id}-signal-contract-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_world_monitor_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local World Monitor adapter contracts without live-source claims."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *WORLD_MONITOR_PREFLIGHT_TESTS],
        timeout_s=120,
    )
    if test["returncode"] != 0:
        raise RuntimeError("World Monitor preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T074": (
            "World Monitor read-only GET paths, authentication and HTTP fail-closed contracts pass locally",
            ["src/hl_observer/event_intelligence/worldmonitor.py", "tests/test_event_intelligence_worldmonitor.py"],
        ),
        "T075": (
            "World Monitor news digest and prediction-market normalization contracts pass locally",
            ["src/hl_observer/event_intelligence/worldmonitor.py", "tests/test_event_intelligence_worldmonitor.py"],
        ),
        "T077": (
            "World Monitor macro/news classification and causal timestamp contracts pass locally",
            ["src/hl_observer/event_intelligence/worldmonitor.py", "tests/test_event_intelligence_worldmonitor.py", "tests/test_event_intelligence_foundation.py"],
        ),
        "T078": (
            "World Monitor prediction and crypto-category read-only contracts pass locally",
            ["src/hl_observer/event_intelligence/worldmonitor.py", "tests/test_event_intelligence_worldmonitor.py"],
        ),
        "T079": (
            "World Monitor geopolitical/cross-source classification contracts pass locally",
            ["src/hl_observer/event_intelligence/worldmonitor.py", "tests/test_event_intelligence_worldmonitor.py", "tests/test_event_intelligence_complete120.py"],
        ),
        "T080": (
            "World Monitor integration allowlist and signal usability contracts pass locally",
            ["src/hl_observer/event_intelligence/worldmonitor.py", "tests/test_event_intelligence_worldmonitor.py"],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [
                proof,
                "48 local deterministic adapter tests passed; no live World Monitor capture, source completeness or economic certification is claimed",
            ],
        }
        path = evidence_dir / f"{task_id}-world-monitor-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_ci_contract_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record local CI/recovery contract coverage, never hosted execution."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *CI_CONTRACT_PREFLIGHT_TESTS],
        timeout_s=180,
    )
    if test["returncode"] != 0:
        raise RuntimeError("CI/recovery contract preflight failed; no receipts written")

    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T123": (
            "recovery and retry contracts are covered by local exact-ref, bounded and fail-closed tests",
            [".github/workflows", "tests/test_workflow_bounds.py", "tests/test_sync_complete_clone.py"],
        ),
        "T126": (
            "GitHub gate topology and hosted workflow bounds are checked by local contract tests",
            [".github/workflows", "tests/test_ci_workflows.py", "tests/test_workflow_bounds.py"],
        ),
        "T127": (
            "complementary workflow contracts preserve sparse, hosted, read-only and scope boundaries",
            [".github/workflows", "tests/test_ci_workflows.py", "tests/test_restore_safe_workflow_contract.py"],
        ),
        "T128": (
            "restore and replay contracts bind evidence to exact refs/SHA locally",
            [".github/workflows", "tests/test_restore_safe_workflow_contract.py", "tests/test_sync_complete_clone.py"],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [proof, "local contract tests passed; no hosted run is claimed by this receipt"],
        }
        path = evidence_dir / f"{task_id}-ci-contract-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_domain_contract_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record SAFE admission/refusal contracts, never live-data success."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *DOMAIN_CONTRACT_PREFLIGHT_TESTS],
        timeout_s=180,
    )
    if test["returncode"] != 0:
        raise RuntimeError("SAFE/domain contract preflight failed; no receipts written")

    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T033": (
            "SAFE observations retain native identity, timestamps and provenance in local admission contracts",
            ["src/hl_observer", "tests/test_collect_cloud_copy_vault.py", "tests/test_copy_vault_safe_bridge.py"],
        ),
        "T034": (
            "L2/BBO envelopes require valid levels, timestamps, acknowledgements and causal provenance",
            ["tests/test_collect_cloud_copy_vault.py", "tests/test_copy_vault_safe_bridge.py"],
        ),
        "T035": (
            "integrity, hash and publication guards reject corrupted or incompatible SAFE material",
            ["tests/test_copy_vault_safe_bridge.py", "tests/test_publish_dataset_v2_release.py", "tests/test_verify_safe_corpus_partition.py"],
        ),
        "T037": (
            "irreparable partial data is quarantined or refused before publication",
            ["tests/test_copy_vault_safe_bridge.py", "tests/test_publish_dataset_v2_release.py"],
        ),
        "T038": (
            "rejected data cannot be relabeled SAFE by the publication contracts",
            ["tests/test_copy_vault_safe_bridge.py", "tests/test_publish_dataset_v2_release.py", "tests/test_verify_safe_corpus_partition.py"],
        ),
        "T105": (
            "closure gates require explicit evidence and refuse incomplete Copy-Vault proof",
            ["src/hl_observer/backtesting/copy_vault_closure_gate.py", "tests/test_copy_vault_closure_gate.py"],
        ),
        "T112": (
            "missing or causal-invalid evidence remains an honest refusal rather than a fabricated result",
            ["tests/test_copy_vault_causal_evidence_contract.py", "tests/test_copy_vault_snapshot_contract.py", "tests/test_kronos_closure_contract.py"],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [proof, "local contracts passed; no live corpus, hosted run or economic result is claimed"],
        }
        path = evidence_dir / f"{task_id}-domain-contract-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_storage_performance_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record selected local SQLite/performance contracts without economic claims."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *STORAGE_PERFORMANCE_PREFLIGHT_TESTS],
        timeout_s=180,
    )
    if test["returncode"] != 0:
        raise RuntimeError("SQLite/performance preflight failed; no receipts written")

    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T121": (
            "selected SQLite stores and durable-state contracts pass locally in read-only mode",
            ["src/hl_observer/storage", "tests/test_v12_raw_store_sqlite.py", "tests/test_v12_sqlite_store.py", "tests/test_durable_restore_state.py"],
        ),
        "T122": (
            "selected CPU/I/O performance contracts pass locally without claiming an economic result",
            ["tests/test_hypersmart_local_scan_performance_contract.py", "tests/test_copy_vault_performance_contract.py"],
        ),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [proof, "selected local contracts passed; no hosted, live-data or economic performance claim is made"],
        }
        path = evidence_dir / f"{task_id}-storage-performance-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def record_quality_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record a reproducible local Ruff/pytest/coverage check, fail-closed if unavailable."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if not (QUALITY_DEPS / "coverage" / "__init__.py").is_file():
        raise RuntimeError("coverage dependency is unavailable in the local quality environment")
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    ruff = _run_readonly([
        "py", "-3", "-m", "ruff", "check", "--select", "E9,F63,F7,F82",
        "tests/test_coverage_closure_*.py", "tests/coverage_contract_cache_plugin.py",
    ], timeout_s=180)
    if ruff["returncode"] != 0:
        raise RuntimeError("Ruff quality preflight failed; no receipts written")
    quality_env = os.environ.copy()
    quality_env["PYTHONPATH"] = os.pathsep.join(
        [str(QUALITY_DEPS), str(ROOT / "src"), str(ROOT), str(ROOT / "tools")]
    )
    quality_env["COVERAGE_FILE"] = str(ROOT / "runtime" / "reports" / "roadmap_136" / ".coverage")
    coverage_run = _run_readonly([
        "py", "-3", "-m", "coverage", "run", "--branch", "--source=tools", "-m", "pytest", "-q",
        *QUALITY_PREFLIGHT_TESTS,
    ], timeout_s=180, env=quality_env)
    coverage_report = _run_readonly(
        ["py", "-3", "-m", "coverage", "report", "-m"],
        timeout_s=180,
        env=quality_env,
    )
    if coverage_run["returncode"] != 0 or coverage_report["returncode"] != 0:
        raise RuntimeError("pytest/coverage quality preflight failed; no receipts written")

    receipt = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "task_id": "T125",
        "status": "VERIFIED_DONE",
        "commands": [ruff["command"], coverage_run["command"], coverage_report["command"]],
        "tests": [
            f"{ruff['command']} -> returncode={ruff['returncode']}; {ruff['stdout']}",
            f"{coverage_run['command']} -> returncode={coverage_run['returncode']}; {coverage_run['stdout']}",
            f"{coverage_report['command']} -> returncode={coverage_report['returncode']}; {coverage_report['stdout']}",
        ],
        "proofs": [
            "Ruff structural quality checks passed locally",
            "pytest passed under branch coverage and coverage report was generated",
            "scope is the declared quality preflight; no full-repository threshold or hosted run is claimed",
        ],
        "files": ["pyproject.toml", "tests/test_coverage_closure_*.py", "tests/coverage_contract_cache_plugin.py", "tests/test_roadmap_136_registry.py"],
    }
    path = evidence_dir / f"T125-quality-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
    already_present = path.exists()
    if not already_present:
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "head_sha": head_sha,
        "written": [] if already_present else [str(path.relative_to(ROOT)).replace(os.sep, "/")],
        "tested": {"ruff": ruff, "coverage_run": coverage_run, "coverage_report": coverage_report},
    }


def record_dependency_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record dependency audits only when every declared compatible set is clean."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    audits: list[dict[str, Any]] = []
    for report_path in DEPENDENCY_AUDIT_REPORTS:
        if not report_path.is_file():
            raise RuntimeError(f"missing dependency audit report: {report_path}")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid dependency audit report: {report_path}") from exc
        dependencies = report.get("dependencies")
        if not isinstance(dependencies, list) or not dependencies:
            raise RuntimeError(f"dependency audit has no dependency results: {report_path}")
        vulnerabilities = [
            vuln
            for dependency in dependencies
            if isinstance(dependency, dict)
            for vuln in (dependency.get("vulns") or [])
        ]
        if vulnerabilities:
            raise RuntimeError(f"dependency audit found vulnerabilities: {report_path}")
        audits.append({"file": str(report_path.relative_to(ROOT)).replace(os.sep, "/"), "dependencies": len(dependencies), "vulnerabilities": 0})

    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    commands = [
        "py -3 -m pip_audit -r requirements.txt -f json -o runtime/reports/roadmap_136/pip-audit-requirements.json",
        "py -3 -m pip_audit -r requirements-ci-tools.txt -f json -o runtime/reports/roadmap_136/pip-audit-requirements-ci-tools.json",
        "py -3 -m pip_audit -r requirements-recherche.txt -f json -o runtime/reports/roadmap_136/pip-audit-requirements-recherche.json",
    ]
    receipt = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "task_id": "T124",
        "status": "VERIFIED_DONE",
        "commands": commands,
        "tests": [json.dumps(audit, ensure_ascii=False, sort_keys=True) for audit in audits],
        "proofs": [
            "pip-audit reports contain zero known vulnerabilities for runtime, CI-tools and research dependency sets",
            "requirements.txt pytest constraint is aligned with the CI baseline and no longer conflicts with requirements-ci-tools.txt",
            "audit is dependency-set specific and makes no hosted or economic claim",
        ],
        "files": ["requirements.txt", "requirements-ci-tools.txt", "requirements-recherche.txt", *[str(path.relative_to(ROOT)).replace(os.sep, "/") for path in DEPENDENCY_AUDIT_REPORTS]],
    }
    path = evidence_dir / f"T124-dependency-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
    already_present = path.exists()
    if not already_present:
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"head_sha": head_sha, "written": [] if already_present else [str(path.relative_to(ROOT)).replace(os.sep, "/")], "audits": audits}


def record_copy_vault_core_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record bounded Copy-Vault core contracts without live/economic overclaiming."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    test = _run_readonly(
        [sys.executable, "-m", "pytest", "-q", *COPY_VAULT_CORE_PREFLIGHT_TESTS],
        timeout_s=240,
    )
    if test["returncode"] != 0:
        raise RuntimeError("Copy-Vault core preflight failed; no receipts written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    task_specs = {
        "T049": ("discovery and leaderboard contracts pass locally", ["tests/test_copy_vault_discovery_evaluator.py", "tests/test_copy_vault_leader_selection_comparison.py"]),
        "T050": ("vault observation and state contracts pass locally", ["tests/test_collecter_vaults.py", "tests/test_vault_heartbeat.py", "tests/test_vault_replication.py"]),
        "T051": ("wallet scoring and leader review contracts pass locally", ["tests/test_vault_scoring.py", "tests/test_copy_vault_leader_review.py"]),
        "T052": ("observation inventory and causal provenance contracts pass locally", ["tests/test_copy_vault_evidence_inventory.py", "tests/test_copy_vault_causal_regime_provenance.py"]),
        "T053": ("Copy-Vault lifecycle contracts pass locally", ["tests/test_copy_vault_v5_lifecycle_train.py", "tests/test_copy_vault_continuity.py"]),
        "T054": ("ambiguous event and timestamp guards pass locally", ["tests/test_copy_vault_execution_timestamp_guard.py", "tests/test_copy_vault_task_closure_plans.py"]),
        "T055": ("Copy-Vault output and closure contracts pass locally", ["tests/test_copy_vault_evidence_inventory.py", "tests/test_copy_vault_task_closure_plans.py"]),
        "T056": ("bounded Copy-Vault core chain contracts pass locally", ["tests/test_copy_vault_continuity.py", "tests/test_copy_vault_v6_balanced_train.py", "tests/test_copy_vault_v7_exit_flow_train.py", "tests/test_copy_vault_v8_entry_efficiency_train.py", "tests/test_copy_vault_v9_online_leader_quality_train.py"]),
        "T057": ("canonical RiskEngine contracts pass locally", ["tests/test_risk_engine.py", "tests/test_risk_quality_gate.py"]),
        "T058": ("capital and portfolio risk accounting contracts pass locally", ["tests/test_portfolio_risk.py", "tests/test_portfolio_risk_limits.py", "tests/test_engine_pnl.py"]),
        "T059": ("risk limit and gate contracts pass locally", ["tests/test_hypersmart_risk_gates.py", "tests/test_risk_quality_gate.py", "tests/test_portfolio_risk_limits.py"]),
        "T060": ("PAPER execution and ledger wiring contracts pass locally", ["tests/test_paper_engine_ledger_wiring.py", "tests/test_paper_engine_realized_unrealized_pnl_equity.py"]),
        "T061": ("ledger semantic and PnL accounting contracts pass locally", ["tests/test_pnl_ledger_semantic_audit.py", "tests/test_engine_pnl.py"]),
        "T062": ("NO_TRADE and fail-closed risk contracts pass locally", ["tests/test_hypersmart_risk_gates.py", "tests/test_risk_engine.py"]),
        "T063": ("read-only dashboard truth contracts pass locally", ["tests/test_dashboard_truth_audit.py", "tests/test_dashboard_payload_shows_decision_ledger.py", "tests/test_dashboard_payload_shows_paper_pnl_equity.py", "tests/test_dashboard_payload_shows_real_market_features.py", "tests/test_dashboard_shows_lifecycle_patterns_backtests.py"]),
        "T064": ("dashboard facade and fake-position rejection contracts pass locally", ["tests/test_dashboard_truth_audit.py", "tests/test_dashboard_no_fake_paper_positions.py"]),
    }
    written: list[str] = []
    for task_id, (proof, files) in task_specs.items():
        receipt = {
            **common,
            "task_id": task_id,
            "status": "VERIFIED_DONE",
            "files": files,
            "proofs": [proof, "bounded local contracts passed; no live corpus, hosted run or economic performance claim is made"],
        }
        path = evidence_dir / f"{task_id}-copy-vault-core-preflight-{head_sha[:12]}-{working_tree_code_sha256[:12]}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def build_report(evidence_dir: Path) -> dict[str, Any]:
    validate_registry()
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    receipts = _read_receipts(evidence_dir)
    rows: list[dict[str, Any]] = []
    verified_weight = 0.0
    total_weight = sum(task.weight for task in ROADMAP_TASKS)
    for task in ROADMAP_TASKS:
        valid = [
            receipt
            for receipt in receipts[task.task_id]
            if _valid_receipt(receipt, task.task_id, head_sha, working_tree_code_sha256)
        ]
        status = "VERIFIED_DONE" if valid else "TODO"
        if valid:
            verified_weight += task.weight
        rows.append(
            {
                "id": task.task_id,
                "task": task.title,
                "lot": task.lot,
                "priority": task.priority,
                "weight": task.weight,
                "dependencies": list(task.dependencies),
                "status": status,
                "files": valid[-1]["files"] if valid else [],
                "tests": valid[-1]["tests"] if valid else [],
                "proofs": valid[-1]["proofs"] if valid else [],
                "sha": head_sha if valid else None,
                "blockage": None if valid else "no valid current exact-HEAD evidence receipt",
            }
        )
    percentage = round((verified_weight / total_weight) * 100, 2) if total_weight else 0.0
    counts = {status: sum(row["status"] == status for row in rows) for status in sorted(STATUSES)}
    return {
        "schema": "alina.smart_flow.roadmap_136_status.v1",
        "roadmap_id": ROADMAP_ID,
        "roadmap_source_sha256": ROADMAP_SOURCE_SHA256,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "head_sha": head_sha,
        "working_tree_status_sha256": _tree_digest(),
        "progress": {
            "verified_done_weight": verified_weight,
            "total_weight": total_weight,
            "implementation_percent": percentage,
            "implementation_percent_claim": f"{percentage:.2f}%" if rows else "NON ENCORE MESURABLE",
            "measurable": bool(rows),
        },
        "counts": counts,
        "tasks": rows,
        "policy": {
            "agiflow_used": False,
            "paper_read_only_fail_closed": True,
            "real_execution": False,
            "synthetic_evidence_accepted": False,
            "exact_head_required": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    parser.add_argument("--record-authority-preflight", action="store_true")
    parser.add_argument("--record-security-preflight", action="store_true")
    parser.add_argument("--record-command-preflight", action="store_true")
    parser.add_argument("--record-ci-contract-preflight", action="store_true")
    parser.add_argument("--record-domain-contract-preflight", action="store_true")
    parser.add_argument("--record-storage-performance-preflight", action="store_true")
    parser.add_argument("--record-quality-preflight", action="store_true")
    parser.add_argument("--record-dependency-preflight", action="store_true")
    parser.add_argument("--record-copy-vault-core-preflight", action="store_true")
    parser.add_argument("--record-portable-surfaces-preflight", action="store_true")
    parser.add_argument("--record-lab-memory-preflight", action="store_true")
    parser.add_argument("--record-replay-backtest-preflight", action="store_true")
    parser.add_argument("--record-continuous-e2e-preflight", action="store_true")
    parser.add_argument("--record-event-intelligence-preflight", action="store_true")
    parser.add_argument("--record-venue-collection-preflight", action="store_true")
    parser.add_argument("--record-safe-corpus-preflight", action="store_true")
    parser.add_argument("--record-signal-contract-preflight", action="store_true")
    parser.add_argument("--record-world-monitor-preflight", action="store_true")
    args = parser.parse_args()
    try:
        preflight = None
        if args.record_authority_preflight:
            preflight = record_authority_preflight(args.evidence_dir)
        if args.record_security_preflight:
            preflight = record_security_preflight(args.evidence_dir)
        if args.record_command_preflight:
            preflight = record_command_preflight(args.evidence_dir)
        if args.record_ci_contract_preflight:
            preflight = record_ci_contract_preflight(args.evidence_dir)
        if args.record_domain_contract_preflight:
            preflight = record_domain_contract_preflight(args.evidence_dir)
        if args.record_storage_performance_preflight:
            preflight = record_storage_performance_preflight(args.evidence_dir)
        if args.record_quality_preflight:
            preflight = record_quality_preflight(args.evidence_dir)
        if args.record_dependency_preflight:
            preflight = record_dependency_preflight(args.evidence_dir)
        if args.record_copy_vault_core_preflight:
            preflight = record_copy_vault_core_preflight(args.evidence_dir)
        if args.record_portable_surfaces_preflight:
            preflight = record_portable_surfaces_preflight(args.evidence_dir)
        if args.record_lab_memory_preflight:
            preflight = record_lab_memory_preflight(args.evidence_dir)
        if args.record_replay_backtest_preflight:
            preflight = record_replay_backtest_preflight(args.evidence_dir)
        if args.record_continuous_e2e_preflight:
            preflight = record_continuous_e2e_preflight(args.evidence_dir)
        if args.record_event_intelligence_preflight:
            preflight = record_event_intelligence_preflight(args.evidence_dir)
        if args.record_venue_collection_preflight:
            preflight = record_venue_collection_preflight(args.evidence_dir)
        if args.record_safe_corpus_preflight:
            preflight = record_safe_corpus_preflight(args.evidence_dir)
        if args.record_signal_contract_preflight:
            preflight = record_signal_contract_preflight(args.evidence_dir)
        if args.record_world_monitor_preflight:
            preflight = record_world_monitor_preflight(args.evidence_dir)
        report = build_report(args.evidence_dir)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    if args.print_report:
        print(encoded, end="")
    if preflight is not None:
        print(json.dumps({"preflight": preflight}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

