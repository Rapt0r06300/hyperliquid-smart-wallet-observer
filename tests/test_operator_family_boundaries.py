from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write_status_pair(tmp_path: Path, family: str, config_family: str | None = None) -> tuple[Path, Path]:
    request_id = "a" * 64
    config = {"strategy_family": config_family} if config_family else {}
    intent = {
        "schema_version": "alina.operator_intent.v2",
        "intent": "backtest",
        "request_id": request_id,
        "phase": "ANALYZE",
        "phase_epoch": 2,
        "analysis_stage": "BACKTEST",
        "source_collection_epoch": 1,
        "collection_cutoff_at_utc": "2026-10-26T00:00:00Z",
        "config": config,
        "strategy_family": family,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    digest = hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    status = {
        "schema_version": "alina.operator_status.v2",
        "request_id": request_id,
        "intent": "backtest",
        "intent_digest": digest,
        "state": "DISPATCHED",
        "terminal": False,
        "phase": "ANALYZE",
        "phase_epoch": 2,
        "analysis_stage": "BACKTEST",
        "source_collection_epoch": 1,
        "collection_cutoff_at_utc": "2026-10-26T00:00:00Z",
        "strategy_family": family,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    intent_path, status_path = tmp_path / "intent.json", tmp_path / "status.json"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    status_path.write_text(json.dumps(status), encoding="utf-8")
    return intent_path, status_path


def test_operator_status_validator_rejects_disabled_family(tmp_path: Path) -> None:
    intent, status = _write_status_pair(tmp_path, "lead_lag", "lead_lag")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_operator_status.py"), "--intent", str(intent), "--status", str(status)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "DISABLED_BY_SCOPE" in result.stderr


def test_operator_status_validator_requires_canonical_family_in_record(tmp_path: Path) -> None:
    intent, status = _write_status_pair(tmp_path, "all")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_operator_status.py"), "--intent", str(intent), "--status", str(status)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "OPERATOR_INTENT_FAMILY_MISMATCH" in result.stderr


def test_operator_status_validator_accepts_pinned_copy_vault(tmp_path: Path) -> None:
    intent, status = _write_status_pair(tmp_path, "copy_vault", "copy_vault")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_operator_status.py"), "--intent", str(intent), "--status", str(status)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"valid": true' in result.stdout


def test_intent_importer_refuses_disabled_family_before_materialization(tmp_path: Path) -> None:
    alina_root = tmp_path / "alina"
    scope = alina_root / "src" / "hl_observer" / "strategies" / "active_scope.py"
    scope.parent.mkdir(parents=True)
    scope.write_bytes((ROOT / "src" / "hl_observer" / "strategies" / "active_scope.py").read_bytes())
    intent_root = alina_root / "control" / "operator-intents"
    intent_root.mkdir(parents=True)
    request_id = "b" * 64
    intent = {
        "schema_version": "alina.operator_intent.v2",
        "intent": "backtest",
        "request_id": request_id,
        "phase": "ANALYZE",
        "phase_epoch": 2,
        "analysis_stage": "BACKTEST",
        "source_collection_epoch": 1,
        "collection_cutoff_at_utc": "2026-10-26T00:00:00Z",
        "config": {"strategy_family": "lead_lag"},
        "strategy_family": "lead_lag",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    (intent_root / f"{request_id}.json").write_text(json.dumps(intent), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "import_operator_intents.py"),
            "--alina-root",
            str(alina_root),
            "--phase",
            "ANALYZE",
            "--phase-epoch",
            "2",
            "--analysis-stage",
            "BACKTEST",
            "--source-collection-epoch",
            "1",
            "--collection-cutoff-at-utc",
            "2026-10-26T00:00:00Z",
            "--code-sha",
            "c" * 40,
            "--dataset-repo-sha",
            "d" * 40,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "DISABLED_BY_SCOPE" in result.stderr
    assert not (tmp_path / "catalog" / "campaigns").exists()


def _write_receipt_tree(root: Path, family: str) -> None:
    request_id, campaign_id = "e" * 64, "operator-" + "e" * 32 + "-backtest"
    receipt_dir = root / "catalog" / "dispatch-receipts"
    campaign_dir = root / "catalog" / "campaigns"
    receipt_dir.mkdir(parents=True)
    campaign_dir.mkdir(parents=True)
    receipt = {
        "schema": "alina.dispatch_receipt.v1",
        "request_id": request_id,
        "campaign_id": campaign_id,
        "main_code_sha": "1" * 40,
        "dataset_repo_sha": "2" * 40,
        "creation_phase": "ANALYZE",
        "phase_epoch": 2,
        "source_collection_epoch": 1,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "strategy_family": family,
    }
    campaign = {
        "schema_version": "alina.resumable_campaign.v2",
        "campaign_id": campaign_id,
        "operator_request_id": request_id,
        "code_sha": "1" * 40,
        "creation_phase": "ANALYZE",
        "phase_epoch": 2,
        "source_collection_epoch": 1,
        "collection_cutoff_at_utc": "2026-10-26T00:00:00Z",
        "dataset_selection_id": "f" * 64,
        "kind": "backtest",
        "cursor": {"operator_intent": "backtest", "strategy_family": family},
    }
    (receipt_dir / f"{campaign_id}.json").write_text(json.dumps(receipt), encoding="utf-8")
    (campaign_dir / f"{campaign_id}.json").write_text(json.dumps(campaign), encoding="utf-8")


def test_receipt_validator_rejects_v2_campaign_outside_active_scope(tmp_path: Path) -> None:
    _write_receipt_tree(tmp_path, "lead_lag")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_dispatch_receipts.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "DISABLED_BY_SCOPE" in result.stderr


def test_operator_workflows_use_the_same_family_normalizer() -> None:
    intent_workflow = (ROOT / ".github" / "workflows" / "alina-operator-intent.yml").read_text()
    dispatch_workflow = (ROOT / ".github" / "workflows" / "alina-operator-dispatch.yml").read_text()

    assert "from operator_family_contract import normalize_operator_family" in intent_workflow
    assert "from operator_family_contract import normalize_operator_family" in dispatch_workflow
    assert '"strategy_family":family' in intent_workflow
    assert "strategy_family:\n        description:" in dispatch_workflow
    assert "options: [all, copy_vault]" in intent_workflow
