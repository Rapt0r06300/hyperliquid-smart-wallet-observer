"""Local, fail-closed proof contracts for ASF-RIG-001..020.

These tests verify the safety and provenance boundaries implemented by the
responsible modules.  They do not manufacture market observations, fills,
PnL, or hosted-run results; economic/data-dependent gates remain explicitly
unmeasurable when their source evidence is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

from check_repo_governance import local_failures
from hl_observer.backtest.no_lookahead_guard import (
    assert_no_lookahead,
    find_lookahead_violations,
)
from hl_observer.backtest.runtime_parity import (
    parity_commit_receipt,
    parity_replay_receipt,
)
from hl_observer.backtest.walk_forward import (
    walk_forward_partition_receipt,
    walk_forward_safety_receipt,
)
from hl_observer.datasets.dataset_untrusted_guard import (
    dataset_contract_receipt,
    dataset_partial_replay_receipt,
    dataset_unique_counts_receipt,
    dataset_zip_slip_receipt,
)
from hl_observer.market_data.live_l2_service import (
    native_l2_done_receipt,
    native_l2_gap_receipt,
    native_l2_order_receipt,
)
from hl_observer.simulation.economic_freeze_registry import (
    economic_freeze_safety_receipt,
)
from hl_observer.simulation.paper_ledger import (
    ledger_commit_receipt,
    paper_ledger_safety_receipt,
    PaperLedger,
)
from hl_observer.simulation.scoreboard_promotion import (
    scoreboard_promotion_safety_receipt,
)
from hl_observer.strategies.active_scope import (
    build_official_scope_environment,
    continuous_collection_receipt,
    copy_vault_only_receipt,
    fail_closed_scope_receipt,
    verify_official_runtime_scope,
)
from tools.alina_roadmap_progress import receipt_is_verified
from tools.sync_complete_clone import sync_clone_safety_receipt


ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "roadmap" / "ALINA_ROADMAP_3120.json"
RECEIPTS = ROOT / "runtime" / "roadmap" / "ALINA_ROADMAP_3120.receipts.jsonl"


def test_rig_001_roadmap_has_exact_contiguous_ids() -> None:
    tasks = json.loads(ROADMAP.read_text(encoding="utf-8"))["tasks"]
    ordinals = [int(task["ordinal"]) for task in tasks]
    ids = [str(task["id"]) for task in tasks]
    assert len(tasks) == 3120
    assert ordinals == list(range(1, 3121))
    assert len(ids) == len(set(ids)) == 3120


def test_rig_002_authority_and_receipt_verifier_are_present() -> None:
    for relative in (
        "AGENTS.md",
        "SECURITY.md",
        "docs/HYPERSMART_CONSTITUTION.md",
        "docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md",
        "docs/LOIS_MESUREES.md",
        "CLAUDE.md",
    ):
        assert (ROOT / relative).is_file()
    tracker = (ROOT / "tools" / "alina_roadmap_progress.py").read_text(encoding="utf-8")
    assert "receipt_is_verified" in tracker
    assert "closure_allowed" in tracker
    assert "never infers completion" in tracker


def test_rig_003_repository_governance_has_no_transactional_gap() -> None:
    assert local_failures() == []
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
    assert "paper" in security and "read-only" in security
    assert "testnet" in security


def test_rig_004_copy_vault_is_the_only_materializing_family() -> None:
    valid, reasons = verify_official_runtime_scope({"HYPERSMART_ACTIVE_STRATEGY_SCOPE": "copy_vault"})
    assert valid and reasons == ()
    assert copy_vault_only_receipt(("copy_vault",))["status"] == "PROVEN"
    assert fail_closed_scope_receipt("lead_lag")["status"] == "PROVEN"
    assert verify_official_runtime_scope({"HYPERSMART_ACTIVE_STRATEGIES": "lead_lag"})[0] is False
    assert build_official_scope_environment({})["HYPERSMART_SCOPE_OVERRIDE_ALLOWED"] == "0"


def test_rig_005_collection_continuity_is_bounded_and_fail_closed() -> None:
    assert continuous_collection_receipt(
        checkpoint_age_ms=5, max_age_ms=10, collection_active=True
    )["status"] == "PROVEN"
    failed = continuous_collection_receipt(
        checkpoint_age_ms=11, max_age_ms=10, collection_active=True
    )
    assert failed["status"] == "REJECTED" and failed["fail_closed"] is True


def test_rig_006_dataset_identity_requires_safe_manifest_and_digest() -> None:
    manifest = {
        "dataset_id": "safe-copy-vault",
        "status": "SAFE",
        "manifest_sha256": "a" * 64,
        "replay_compatible": True,
        "publication_complete": True,
    }
    assert dataset_contract_receipt(manifest)["status"] == "PROVEN"
    rejected = dataset_contract_receipt({**manifest, "status": "PARTIAL"})
    assert rejected["status"] == "UNMEASURABLE" and rejected["fail_closed"] is True


def test_rig_007_dataset_counts_require_exact_unique_observations() -> None:
    assert dataset_unique_counts_receipt(
        total_count=3, unique_count=3, unique_ids=("a", "b", "c")
    )["status"] == "PROVEN"
    assert dataset_unique_counts_receipt(
        total_count=3, unique_count=2, unique_ids=("a", "b", "b")
    )["status"] == "REJECTED"


def test_rig_008_l2_order_and_gap_contracts_refuse_incomplete_sequences() -> None:
    assert native_l2_order_receipt(sequences=(1, 2, 3))["status"] == "PROVEN"
    assert native_l2_gap_receipt(sequences=(1, 2, 3))["status"] == "PROVEN"
    assert native_l2_gap_receipt(sequences=(1, 3))["status"] == "REJECTED"
    assert native_l2_done_receipt(
        status="PROVEN", coverage_status="PROVEN", proof_ids=("l2-proof",), replay_verified=True
    )["status"] == "PROVEN"


def test_rig_009_partial_and_untrusted_data_never_promote() -> None:
    assert dataset_zip_slip_receipt("../outside.jsonl")["status"] == "PROVEN"
    assert dataset_partial_replay_receipt(status="PARTIAL", replayable=False)["status"] == "PROVEN"
    unsafe = dataset_partial_replay_receipt(status="PARTIAL", replayable=True)
    assert unsafe["status"] == "REJECTED" and unsafe["fail_closed"] is True


def test_rig_010_clone_contract_is_non_destructive() -> None:
    state = {
        "branch": "main",
        "tracked_clean": True,
        "origin_trusted": True,
        "force_push": False,
        "reset": False,
        "clean": False,
    }
    assert sync_clone_safety_receipt(state)["status"] == "PROVEN"
    assert sync_clone_safety_receipt({**state, "force_push": True})["status"] == "REJECTED"


def test_rig_011_runtime_replay_contract_requires_deterministic_outputs() -> None:
    assert parity_replay_receipt(outputs=(("decision", "NO_GO"),) * 2)["status"] == "PROVEN"
    assert parity_replay_receipt(outputs=(("a",), ("b",)))["status"] == "REJECTED"


def test_rig_012_paper_ledger_preserves_chain_and_atomic_commit() -> None:
    assert paper_ledger_safety_receipt(PaperLedger(session_id="rig-paper"))["status"] == "PROVEN"
    assert ledger_commit_receipt(crashed=True, committed=False, checkpoint_saved=True)["status"] == "PROVEN"
    assert ledger_commit_receipt(crashed=True, committed=True, checkpoint_saved=False)["status"] == "REJECTED"


def test_rig_013_no_lookahead_rejects_future_data() -> None:
    assert find_lookahead_violations([(100, 99)]) == []
    assert_no_lookahead([(100, 99)])
    assert len(find_lookahead_violations([(100, 101)])) == 1


def test_rig_014_walk_forward_partitions_are_disjoint_and_fail_closed() -> None:
    assert walk_forward_partition_receipt(
        train_ids=("t1",), oos_ids=("o1",), forward_ids=("f1",)
    )["status"] == "PROVEN"
    assert walk_forward_partition_receipt(
        train_ids=("same",), oos_ids=("same",), forward_ids=("f1",)
    )["status"] == "REJECTED"
    assert walk_forward_safety_receipt({})["status"] == "REJECTED"


def test_rig_015_statistical_contract_does_not_promote_missing_results() -> None:
    assert walk_forward_safety_receipt(
        {
            "train": ("train-proof",),
            "oos": ("oos-proof",),
            "forward": ("forward-proof",),
            "code_sha": "code-proof",
            "data_sha": "data-proof",
            "cutoff_ts_ms": 1,
            "trials": 1,
        }
    )["status"] == "PROVEN"


def test_rig_016_economic_freeze_is_hash_bound_and_paper_only() -> None:
    payload = {
        "schema_version": "hypersmart.economic_parameter_freeze.v1",
        "family": "copy_vault",
        "selected_before_final_evaluation": True,
        "parameters": {"seed": 1},
        "parameters_sha256": "a" * 64,
        "frozen_at_ms": 1,
    }
    result = economic_freeze_safety_receipt(payload)
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
    assert result["status"] in {"PROVEN", "REJECTED"}


def test_rig_017_scoreboard_refuses_unproven_promotion() -> None:
    rejected = scoreboard_promotion_safety_receipt(
        {"promue": True, "paper_only": True, "real_execution": False}
    )
    assert rejected["status"] == "REJECTED" and rejected["fail_closed"] is True


def test_rig_018_workflows_are_cloud_only_and_minimally_scoped() -> None:
    workflow = (ROOT / ".github" / "workflows" / "security-quality.yml").read_text(encoding="utf-8").lower()
    assert "runs-on: ubuntu-latest" in workflow
    assert "self-hosted" not in workflow
    assert "contents: read" in workflow


def test_rig_019_official_launchers_use_portable_safety_contracts() -> None:
    runtime = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace").lower()
    push = (ROOT / "POUSSER-GITHUB-FORCE.cmd").read_text(encoding="utf-8", errors="replace").lower()
    assert "paper" in runtime and "read-only" in runtime
    assert "push force" in push and "aucun telechargement de shards" in push
    sync = (ROOT / "ALINA_SYNC_COMPLETE.cmd").read_text(encoding="utf-8", errors="replace").lower()
    assert "--download-safe" in sync and "--unpack-safe" in sync
    assert "force" not in sync and "reset" not in sync and "clean" not in sync


def test_rig_020_all_current_receipts_are_exactly_revalidated() -> None:
    tasks = json.loads(ROADMAP.read_text(encoding="utf-8"))["tasks"]
    rows = [json.loads(line) for line in RECEIPTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest = {str(row["task_id"]): row for row in rows}
    assert set(latest) >= {str(task["id"]) for task in tasks}
    assert all(
        receipt_is_verified(row, None, ROOT)
        for task in tasks
        for row in (latest[str(task["id"])],)
    )
