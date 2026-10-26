from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import tools.alina_quant_lab_console as lab
from hl_observer.backtesting.copy_vault_v21_frozen import _verified_freeze
from hl_observer.simulation.economic_freeze_registry import parameter_hash
from tools.alina_quant_lab_console import (
    _pytest_counts,
    _run_group,
    _test_groups,
    assess_physical_freeze,
)

ROOT = Path(__file__).resolve().parents[1]
FREEZE_PATH = ROOT / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json"


def test_lab_reports_the_existing_over_limit_freeze_without_modifying_it() -> None:
    before = FREEZE_PATH.read_bytes()

    result = assess_physical_freeze(FREEZE_PATH)

    assert result["status"] == "REJECTED"
    assert result["reason"] == "COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED"
    assert FREEZE_PATH.read_bytes() == before


def test_lab_recognizes_a_valid_physical_freeze_without_promoting_it(
    tmp_path: Path,
) -> None:
    source = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(source)
    params = payload["freeze"]["parameters"]
    params["core_notional_usd"] = 200.0
    payload["freeze"]["parameters_sha256"] = parameter_hash(params)
    target = tmp_path / "freeze.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = assess_physical_freeze(target)

    assert _verified_freeze(payload)["parameters"]["core_notional_usd"] == 200.0
    assert result["status"] == "VALID_PHYSICAL_FREEZE"
    assert result["core_notional_usd"] == 200.0


def test_lab_extracts_independent_pytest_summary_counts() -> None:
    counts = _pytest_counts("= 7 passed, 2 failed, 1 skipped in 3.2s =")

    assert counts["passed"] == 7
    assert counts["failed"] == 2
    assert counts["skipped"] == 1
    assert counts["errors"] == 0


def test_lab_counts_a_single_collection_error() -> None:
    counts = _pytest_counts("1 error, 3 passed in 1.2s")

    assert counts["errors"] == 1
    assert counts["passed"] == 3


def test_dashboard_compares_current_copy_vault_with_challenger(tmp_path: Path) -> None:
    summary = {
        "run_id": "comparison", "head": "abc", "status": "PROMISING",
        "safe_inputs": {"verified_assets": 2, "unique_fills": 3, "unique_books": 4},
        "current_copy_vault": {
            "status": "MEASURED", "validation": {"daily_mean_net_pnl_usd": 1.25},
        },
        "economic_result": {
            "status": "PROMISING", "reason": "heldout pending", "candidates_tested": 12,
            "freeze_created": True, "economically_proven": False,
            "validation": {"daily_mean_net_pnl_usd": 2.75},
        },
        "freeze_verdict": "candidat seulement",
    }

    dashboard = lab._write_economic_html_report(tmp_path, summary).read_text(encoding="utf-8")

    assert "Copy‑Vault actuel" in dashboard
    assert "+1.2500 USD/jour" in dashboard
    assert "+2.7500 USD/jour" in dashboard
    assert "+1.5000 USD/jour" in dashboard
    assert "Amélioration mesurée" in dashboard


def test_dashboard_explains_missing_signal_days_and_safe_payload_rejections(
    tmp_path: Path,
) -> None:
    summary = {
        "run_id": "coverage-blocker", "head": "abc", "status": "MORE_DATA",
        "safe_inputs": {
            "verified_assets": 14_647,
            "expected_safe_shards": 14_647,
            "copy_vault_safe_catalog_shards": 14_847,
            "safe_copy_vault_shards_not_used_for_pnl": 200,
            "safe_copy_vault_shards_not_used_for_pnl_by_family": {
                "copy_vault_positions": 100,
                "copy_vault_selection": 100,
            },
            "safe_copy_vault_shards_not_used_for_pnl_inventory_by_family": {
                "copy_vault_positions": {
                    "catalogue_shards": 100,
                    "local_files_present_unverified": 0,
                    "local_files_missing": 100,
                    "local_files_unsafe": 0,
                },
                "copy_vault_selection": {
                    "catalogue_shards": 100,
                    "local_files_present_unverified": 0,
                    "local_files_missing": 100,
                    "local_files_unsafe": 0,
                },
            },
            "missing_shards": 0,
            "partial_shards_excluded": 10,
            "safe_catalog_status": "SAFE_COMPLETE",
            "data_complete": False,
            "payload_audit": {"INVALID_OR_NONCAUSAL_L2_REJECTED": 2_319},
        },
        "economic_result": {
            "status": "MORE_DATA",
            "reason": "INSUFFICIENT_DISTINCT_SIGNAL_DAYS",
            "candidates_tested": 0,
            "signal_coverage": {
                "distinct_utc_days": 2,
                "minimum_utc_days_required": 6,
                "signal_start_ms": 1_790_867_233_651,
                "signal_end_ms": 1_790_965_255_148,
                "signal_span_hours": 27.228,
            },
        },
    }

    dashboard = lab._write_economic_html_report(tmp_path, summary).read_text(encoding="utf-8")

    assert "2 / 6 jours UTC distincts" in dashboard
    assert "27,228 h" in dashboard or "27.228 h" in dashboard
    assert "2 319" in dashboard or "2,319" in dashboard
    assert "shards PARTIAL exclus : 10" in dashboard
    assert "200 shards SAFE du catalogue hors replay économique" in dashboard
    assert "100 positions" in dashboard and "100 sélection" in dashboard
    assert "0/100 positions fichiers locaux repérés (100 absents)" in dashboard
    assert "0/100 sélection fichiers locaux repérés (100 absents)" in dashboard


def test_dashboard_separates_missing_backfill_audit_from_missing_shards(tmp_path: Path) -> None:
    summary = {
        "run_id": "backfill-audit", "head": "abc", "status": "MORE_DATA",
        "safe_inputs": {
            "verified_assets": 15_256, "expected_safe_shards": 15_256,
            "missing_shards": 0, "unique_fills": 14_285, "unique_books": 50_170,
            "incremental_unique_fills": 0, "historical_unique_fills": 14_285,
            "payload_audit": {"SNAPSHOT_FAMILY_FLAG_MISMATCH": 35},
            "historical_coverage_audit": {
                "expected_release_count": 66, "audited_release_count": 0,
                "durable_receipt_release_count": 66,
                "missing_durable_receipt_tags": [],
                "receipt_without_backfill_audit_tags": [f"tag-{i}" for i in range(66)],
            },
        },
        "economic_result": {"status": "MORE_DATA", "reason": "NO_SAFE_LIVE_FORWARD_FILLS"},
    }

    dashboard = lab._write_economic_html_report(tmp_path, summary).read_text(encoding="utf-8")

    assert "Audit de backfill historique : 0/66" in dashboard
    assert "66/66 reçus durables de collecte" in dashboard
    assert "66 reçu(s) sans audit de backfill et 0 sans reçu durable" in dashboard
    assert "pas le nombre de shards locaux présents" in dashboard
    assert "35 trames userFills sans marqueur isSnapshot valide" in dashboard
    assert "shards locaux absents : 0" in dashboard




def test_lab_fails_closed_when_a_required_test_group_is_empty(tmp_path: Path) -> None:
    result = _run_group("groupe obligatoire", [], tmp_path / "missing.log")

    assert result["status"] == "FAIL"
    assert result["return_code"] != 0


def test_lab_covers_copy_vault_scope_paper_and_readiness_boundaries() -> None:
    groups = _test_groups()
    selected = {path for _name, paths in groups for path in paths}

    assert {
        "tests/test_paper_canonique.py",
        "tests/test_strategy_readiness.py",
        "tests/test_readme_scope_coherence.py",
    } <= selected
    assert all(paths for _name, paths in groups)
    assert sum(len(paths) for _name, paths in groups) == len(selected)


def test_lab_uses_at_most_65_percent_of_logical_cpus(monkeypatch) -> None:
    monkeypatch.setenv("ALINA_QUANT_CPU_PERCENT", "65")
    monkeypatch.setattr(lab.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(
        lab.importlib.util,
        "find_spec",
        lambda name: object() if name == "xdist" else None,
    )

    assert lab._pytest_parallel_args(20) == ["-n", "10", "--dist", "loadfile"]


def test_lab_falls_back_to_serial_when_xdist_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(lab.importlib.util, "find_spec", lambda _name: None)

    assert lab._pytest_parallel_args(20) == []


def test_copy_vault_lab_launcher_checks_complete_test_runtime() -> None:
    launcher = (ROOT / "LANCER_LAB_QUANT_COPY_VAULT.cmd").read_text(
        encoding="utf-8"
    )

    assert "tools\\python\\python.exe" in launcher
    assert "import pytest, typer" in launcher
    assert 'set "ALINA_QUANT_CPU_PERCENT=65"' in launcher
    assert '"%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c' in launcher


def test_lab_writes_complete_reports_when_a_group_is_interrupted(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ALINA_QUANT_NO_OPEN", "1")
    monkeypatch.setattr(lab, "ROOT", tmp_path)
    monkeypatch.setattr(lab, "_restore_processes", lambda: [])
    monkeypatch.setattr(lab, "_test_groups", lambda: [("interrupted", ["test_x.py"])])
    monkeypatch.setattr(
        lab,
        "_run_group",
        lambda *_args, **_kwargs: {
            "name": "interrupted",
            "status": "INTERRUPTED",
            "return_code": 130,
            "counts": lab._pytest_counts(""),
            "seconds": 1.0,
            "cpu_seconds": 0.1,
            "peak_working_set_bytes": 1,
            "log": "interrupted.log",
        },
    )

    assert lab.run_lab() == 130
    reports = list((tmp_path / "runtime" / "reports" / "copy_vault_quant_lab").glob("*"))
    assert len(reports) == 1
    result = json.loads((reports[0] / "resultat.json").read_text(encoding="utf-8"))
    assert result["status"] == "INTERRUPTED"
    assert "**INTERRUPTED**" in (reports[0] / "RAPPORT.md").read_text(encoding="utf-8")
    dashboard = (reports[0] / "RAPPORT.html").read_text(encoding="utf-8")
    assert "Laboratoire CopyVault" in dashboard
    assert "INTERRUPTED" in dashboard
    assert "Meilleure stratégie prouvée" in dashboard


def test_research_mode_refuses_missing_provenance(tmp_path: Path, capsys) -> None:
    from tools.alina_quant_lab_console import main

    assert main(["--research", "--dataset-root", str(tmp_path)]) == 2
    assert "RESEARCH_NO_GO" in capsys.readouterr().out


def test_research_mode_refuses_workspace_without_copy_data(tmp_path: Path, capsys) -> None:
    from tools.alina_quant_lab_console import main

    provenance = tmp_path / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text("{}", encoding="utf-8")
    assert main(["--research", "--dataset-root", str(tmp_path)]) == 2
    assert "aucune source Copy-Vault" in capsys.readouterr().out


def test_research_mode_runs_existing_dataset_campaign(monkeypatch, tmp_path: Path) -> None:
    from tools import alina_quant_lab_console as lab

    provenance = tmp_path / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    provenance.parent.mkdir(parents=True)
    provenance.write_text("{}", encoding="utf-8")
    source = tmp_path / "runtime" / "data" / "vault_fills.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text('{"coin": "BTC"}\\n', encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Finished", (), {"returncode": 0})()

    monkeypatch.setattr(lab.subprocess, "run", fake_run)
    assert lab.main(["--research", "--dataset-root", str(tmp_path)]) == 0
    assert calls
    cmd, kwargs = calls[0]
    assert "--no-start-collection" in cmd
    assert "--root" in cmd
    assert str(tmp_path) in cmd
    assert kwargs["env"]["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert kwargs["env"]["HL_ENABLE_TESTNET_EXECUTION"] == "0"

def test_safe_inspection_does_not_promote_unverified_shards(tmp_path: Path) -> None:
    from tools.alina_quant_lab_console import inspect_local_safe_corpus

    result = inspect_local_safe_corpus(tmp_path)
    assert result["status"] == "NOT_CERTIFIED"
    assert result["safe_registry_rows"] is None


def _write_restore_registry(
    root: Path, *, run_status: str = "COMPLETE", scope: str = "COPY_VAULT_ONLY",
) -> str:
    recovery = root / "runtime" / "recovery" / "full"
    recovery.mkdir(parents=True)
    catalog_path = root / "catalog" / "DATA_INDEX.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text('{"schema":"fixture"}\n', encoding="utf-8")
    catalog = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    families = ["copy_vault_fills", "copy_vault_l2"]
    db = sqlite3.connect(recovery / "SAFE_SHARDS.sqlite3")
    db.execute("CREATE TABLE safe_shard_registry_meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany(
        "INSERT INTO safe_shard_registry_meta VALUES (?, ?)",
        [
            ("run_status", run_status),
            ("active_catalog_sha256", catalog),
            ("target_catalog_sha256", catalog),
        ],
    )
    db.execute("CREATE TABLE current_safe_shards (dataset_id TEXT)")
    db.executemany("INSERT INTO current_safe_shards VALUES (?)", [("fill",), ("book",)])
    db.commit()
    db.close()
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps({
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "status": "REPLAY_READY_COMPLETE",
        "selection_scope": scope,
        "selection_families": families,
        "catalog_verification": {
            "source_index_sha256": catalog,
            "selection_scope": scope,
            "selection_families": families,
        },
        "classification": {
            "materialization_complete": True,
            "expected_usable_shards": 2,
            "usable_shards": 2,
            "failures": [],
        },
    }), encoding="utf-8")
    return catalog


def test_safe_inspection_accepts_compressed_restore_without_unpack_report(tmp_path: Path) -> None:
    from tools.alina_quant_lab_console import inspect_local_safe_corpus

    _write_restore_registry(tmp_path)

    result = inspect_local_safe_corpus(tmp_path)

    assert not (tmp_path / "runtime/recovery/full/UNPACK_REPORT.json").exists()
    assert result["status"] == "RESTORE_RECEIPTS_MATCH_NOT_REHASHED"
    assert result["safe_registry_rows"] == 2
    assert result["selection_scope"] == "COPY_VAULT_ONLY"
    assert "LAB_REHASHES_SHARDS_BEFORE_REPLAY" in result["reason"]


def test_safe_inspection_rejects_registry_while_restore_is_in_progress(tmp_path: Path) -> None:
    from tools.alina_quant_lab_console import inspect_local_safe_corpus

    _write_restore_registry(tmp_path, run_status="IN_PROGRESS")

    result = inspect_local_safe_corpus(tmp_path)

    assert result["status"] == "NOT_CERTIFIED"
    assert result["reason"] == "SAFE_REGISTRY_NOT_FINAL_FOR_ACTIVE_CATALOG"


def test_safe_research_builds_workspace_then_runs_existing_campaign(
    monkeypatch, tmp_path: Path,
) -> None:
    from hl_observer.backtesting import copy_vault_local_lab as local_lab
    from tools import alina_quant_lab_console as lab

    calls = []
    materializations = []
    progress_messages = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Done", (), {"returncode": 0, "stdout": "a" * 40 + "\n"})()

    def fake_materialize(recovery, workspace, *, progress=None):
        materializations.append((recovery, workspace))
        if progress is not None:
            progress("test de progression SAFE")
            progress_messages.append("callback configuré")
        return {
            "status": "UNMEASURABLE", "reason": "NO_SAFE_TEST_FIXTURE",
            "verified_assets": 0, "expected_safe_shards": 0,
            "unique_fills": 0, "unique_books": 0,
        }

    monkeypatch.setattr(lab, "ROOT", tmp_path)
    monkeypatch.setattr(lab, "_open_report", lambda _path: None)
    monkeypatch.setattr(lab.subprocess, "run", fake_run)
    monkeypatch.setattr(local_lab, "materialize_safe_workspace", fake_materialize)
    monkeypatch.setattr(
        local_lab,
        "run_historical_trade_replay",
        lambda *_args, **_kwargs: {"status": "UNMEASURABLE", "trial_count": 0},
    )
    monkeypatch.setattr(local_lab, "load_improvement_history", lambda _root: [])

    assert lab.main(["--safe-research", "--once"]) == 0
    assert len(calls) == 1
    assert calls[0][0] == ["git", "rev-parse", "HEAD"]
    assert len(materializations) == 1
    assert progress_messages == ["callback configuré"]
    recovery, workspace = materializations[0]
    assert recovery == tmp_path / "runtime" / "recovery" / "full"
    assert workspace.name == "workspace"
    assert workspace.parent.parent.name == "copy_vault_quant_lab"
    assert json.loads((workspace.parent / "resultat.json").read_text(encoding="utf-8"))[
        "network_or_collection_started"
    ] is False


def test_safe_research_replays_valid_rows_when_corpus_is_incomplete(
    monkeypatch, tmp_path: Path,
) -> None:
    from hl_observer.backtesting import copy_vault_local_lab as local_lab
    from tools import alina_quant_lab_console as console

    campaign_calls = []
    historical_calls = []

    monkeypatch.setattr(console, "ROOT", tmp_path)
    monkeypatch.setattr(console, "_open_report", lambda _path: None)
    monkeypatch.setattr(
        console.subprocess, "run",
        lambda *_args, **_kwargs: type("Done", (), {
            "returncode": 0, "stdout": "a" * 40 + "\n",
        })(),
    )
    monkeypatch.setattr(
        local_lab, "materialize_safe_workspace",
        lambda *_args, **_kwargs: {
            "status": "MORE_DATA", "reason": "SAFE_PAYLOAD_ROWS_REJECTED",
            "replay_inputs_available": True, "data_complete": False,
            "verified_assets": 12, "expected_safe_shards": 12,
            "unique_fills": 8, "unique_books": 40,
            "missing_shards": 0, "partial_shards_excluded": 0,
            "payload_rejected_records": 2,
        },
    )
    monkeypatch.setattr(
        local_lab, "evaluate_current_copy_vault",
        lambda *_args, **_kwargs: {"status": "UNMEASURABLE", "reason": "INCOMPLETE"},
    )

    def run_campaign(workspace, **kwargs):
        campaign_calls.append((workspace, kwargs))
        return {
            "status": "MORE_DATA", "reason": "NO_SAFE_LIVE_FORWARD_FILLS",
            "candidates_tested": 0, "freeze_created": False,
            "economically_proven": False, "data_complete": False,
        }

    def run_historical(*_args, **_kwargs):
        historical_calls.append(True)
        return {
            "status": "COMPLETED_EXPLORATORY", "trial_count": 99,
            "improvement_found": False,
        }

    monkeypatch.setattr(local_lab, "run_local_campaign", run_campaign)
    monkeypatch.setattr(local_lab, "run_historical_trade_replay", run_historical)
    monkeypatch.setattr(local_lab, "load_improvement_history", lambda _root: [])

    assert console.main(["--safe-research", "--once"]) == 0

    assert len(campaign_calls) == 1
    assert len(historical_calls) == 1
    report = json.loads(next(
        (tmp_path / "runtime/reports/copy_vault_quant_lab").glob("*/resultat.json")
    ).read_text(encoding="utf-8"))
    assert report["status"] == "MORE_DATA"
    assert report["safe_inputs"]["data_complete"] is False
    assert report["economic_result"]["economically_proven"] is False
    assert "aucun fill live causal" in report["freeze_verdict"]


def test_legacy_economic_dispatch_keeps_safe_research_separate(monkeypatch) -> None:
    monkeypatch.setattr(lab, "run_economic_lab", lambda **_kw: 47)
    assert lab.main(["--legacy-local-economic"]) == 47


def test_legacy_economic_missing_optional_module_is_no_go(monkeypatch) -> None:
    import builtins
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "hl_observer.backtesting.copy_vault_local_lab":
            raise ImportError("optional module deliberately absent in clean clone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert lab.run_economic_lab() == 2


def test_launcher_keeps_safe_default_and_local_legacy_mode() -> None:
    source = (ROOT / "LANCER_LAB_QUANT_COPY_VAULT.cmd").read_text(encoding="utf-8")
    assert 'set "ALINA_LAB_MODE=safe"' in source
    assert "--safe-research" in source
    assert '"%ALINA_LAB_MODE%"=="once"' in source
    assert "--safe-research --once" in source
    assert "safe (continu) / once (un passage)" in source
    assert '--legacy-local-economic' in source
    assert '"--tests-only"' not in source
