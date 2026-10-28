from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from hl_observer.backtesting.copy_vault_evidence import (
    build_correction_cycle_bundle,
    create_correction_cycle_bundle,
    snapshot_correction_cycle_artifacts,
    verify_correction_cycle_bundle,
)

HEAD = "d9c3bb92f67c8e3ad3a9ae94d211e6afb9b90918"
EVIDENCE_CATEGORIES = (
    "data", "code", "config", "parameters", "attempts", "costs", "ledger",
    "tests", "verdict", "restoration",
)


def _evidence(*, verdict: str = "MORE_DATA") -> dict[str, dict[str, object]]:
    return {
        category: {
            "status": verdict if category == "verdict" else "UNVERIFIED",
            "details": "No economic value inferred from missing evidence.",
        }
        for category in EVIDENCE_CATEGORIES
    }


def test_bundle_binds_exact_head_categories_and_artifact_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "test-output.txt"
    artifact.write_bytes(b"targeted tests passed\n")

    bundle = build_correction_cycle_bundle(
        cycle_id="cycle-20261028-001",
        head=HEAD,
        evidence=_evidence(),
        artifact_paths=["test-output.txt"],
        repo_root=tmp_path,
    )

    assert bundle["head"] == HEAD
    assert set(bundle["evidence"]) == set(EVIDENCE_CATEGORIES)
    assert bundle["evidence"]["verdict"]["status"] == "MORE_DATA"
    assert bundle["artifacts"] == [{
        "path": "test-output.txt",
        "bytes": len(b"targeted tests passed\n"),
        "sha256": hashlib.sha256(b"targeted tests passed\n").hexdigest(),
    }]
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    expected = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert bundle["bundle_sha256"] == expected


def test_create_is_idempotent_only_for_identical_receipt_and_verifies_artifacts(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "receipt.txt"
    artifact.write_text("original\n", encoding="utf-8")
    bundle = build_correction_cycle_bundle(
        cycle_id="cycle-1", head=HEAD, evidence=_evidence(),
        artifact_paths=["receipt.txt"], repo_root=tmp_path,
    )
    destination = tmp_path / "receipts" / "cycle-1.json"

    first_path = create_correction_cycle_bundle(bundle, destination)
    second_path = create_correction_cycle_bundle(bundle, destination)
    assert first_path == second_path == destination
    assert verify_correction_cycle_bundle(destination, repo_root=tmp_path)["valid"] is True

    artifact.write_text("tampered\n", encoding="utf-8")
    verification = verify_correction_cycle_bundle(destination, repo_root=tmp_path)
    assert verification["valid"] is False
    assert verification["artifact_errors"] == ["receipt.txt: SHA-256 or byte count mismatch"]


def test_create_refuses_to_overwrite_a_different_receipt(tmp_path: Path) -> None:
    destination = tmp_path / "cycle.json"
    destination.write_text('{"existing":true}\n', encoding="utf-8")
    bundle = build_correction_cycle_bundle(
        cycle_id="cycle-1", head=HEAD, evidence=_evidence(), repo_root=tmp_path,
    )

    with pytest.raises(FileExistsError):
        create_correction_cycle_bundle(bundle, destination)
    assert destination.read_text(encoding="utf-8") == '{"existing":true}\n'


def test_verifier_rejects_a_rehashed_bundle_with_missing_proof_domains(
    tmp_path: Path,
) -> None:
    bundle = build_correction_cycle_bundle(
        cycle_id="cycle-1", head=HEAD, evidence=_evidence(), repo_root=tmp_path,
    )
    bundle["evidence"].pop("costs")
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    receipt = tmp_path / "forged-incomplete.json"
    receipt.write_text(json.dumps(bundle), encoding="utf-8")

    verification = verify_correction_cycle_bundle(receipt, repo_root=tmp_path)
    assert verification["valid"] is False
    assert "missing evidence categories" in verification["bundle_error"]


@pytest.mark.parametrize("artifact_path", ["../outside.txt", "C:/outside.txt", "/outside.txt"])
def test_bundle_rejects_artifact_paths_outside_repository(
    tmp_path: Path, artifact_path: str,
) -> None:
    with pytest.raises(ValueError, match="relative path inside repository"):
        build_correction_cycle_bundle(
            cycle_id="cycle-1", head=HEAD, evidence=_evidence(),
            artifact_paths=[artifact_path], repo_root=tmp_path,
        )


def test_bundle_requires_complete_evidence_and_a_full_commit_sha(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence.pop("costs")
    with pytest.raises(ValueError, match="missing evidence categories"):
        build_correction_cycle_bundle(
            cycle_id="cycle-1", head=HEAD, evidence=evidence, repo_root=tmp_path,
        )

    with pytest.raises(ValueError, match="full hexadecimal commit SHA"):
        build_correction_cycle_bundle(
            cycle_id="cycle-2", head="d9c3bb9", evidence=_evidence(), repo_root=tmp_path,
        )


def test_bundle_rejects_non_string_evidence_status_without_leaking_type_error(
    tmp_path: Path,
) -> None:
    evidence = _evidence()
    evidence["costs"]["status"] = ["UNVERIFIED"]

    with pytest.raises(ValueError, match="invalid status"):
        build_correction_cycle_bundle(
            cycle_id="cycle-1", head=HEAD, evidence=evidence, repo_root=tmp_path,
        )


def test_verified_evidence_must_reference_a_hashed_bundle_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "test-results.json"
    artifact.write_text('{"passed":true}\n', encoding="utf-8")
    evidence = _evidence()
    evidence["tests"] = {
        "status": "VERIFIED",
        "details": "Targeted tests passed.",
        "artifact_refs": ["missing-results.json"],
    }

    with pytest.raises(ValueError, match="must reference listed artifacts"):
        build_correction_cycle_bundle(
            cycle_id="cycle-1", head=HEAD, evidence=evidence,
            artifact_paths=["test-results.json"], repo_root=tmp_path,
        )


def test_snapshot_preserves_exact_source_bytes_after_working_file_changes(tmp_path: Path) -> None:
    source = tmp_path / "src" / "module.py"
    source.parent.mkdir()
    source.write_bytes(b"original implementation\n")
    snapshots = snapshot_correction_cycle_artifacts(
        repo_root=tmp_path,
        artifact_paths=["src/module.py"],
        snapshot_dir="runtime/cycles/cycle-1/artifacts",
    )
    snapshot_path = snapshots[0]["snapshot_path"]
    source.write_bytes(b"later implementation\n")

    evidence = _evidence()
    evidence["code"] = {
        "status": "VERIFIED",
        "details": "The receipt references the frozen source snapshot.",
        "artifact_refs": [snapshot_path],
    }
    bundle = build_correction_cycle_bundle(
        cycle_id="cycle-1", head=HEAD, evidence=evidence,
        artifact_paths=[snapshot_path],
        artifact_origins={snapshot_path: snapshots[0]["source_path"]},
        repo_root=tmp_path,
    )
    receipt = tmp_path / "runtime/cycles/cycle-1/EVIDENCE.json"
    create_correction_cycle_bundle(bundle, receipt)

    assert (tmp_path / snapshot_path).read_bytes() == b"original implementation\n"
    assert bundle["artifacts"][0]["origin"] == "src/module.py"
    assert verify_correction_cycle_bundle(receipt, repo_root=tmp_path)["valid"] is True


def test_cycle_reconstruction_matches_frozen_receipt_hashes_and_verdict(
    tmp_path: Path,
) -> None:
    run_receipt = {
        "cycle_id": "cycle-reconstruct",
        "head": HEAD,
        "economic_verdict": "UNMEASURABLE",
        "net_pnl_usd": None,
    }
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps(run_receipt, sort_keys=True), encoding="utf-8")
    snapshot = snapshot_correction_cycle_artifacts(
        repo_root=tmp_path,
        artifact_paths=["run.json"],
        snapshot_dir="runtime/cycles/reconstruct/artifacts",
    )[0]["snapshot_path"]
    evidence = _evidence(verdict="UNMEASURABLE")
    evidence["tests"] = {
        "status": "VERIFIED",
        "details": "The test report is preserved as an immutable artifact.",
        "artifact_refs": [snapshot],
    }
    evidence["verdict"]["artifact_refs"] = [snapshot]
    bundle = build_correction_cycle_bundle(
        cycle_id=run_receipt["cycle_id"], head=HEAD, evidence=evidence,
        artifact_paths=[snapshot], artifact_origins={snapshot: "run.json"},
        repo_root=tmp_path,
    )
    bundle_path = tmp_path / "runtime/cycles/reconstruct/EVIDENCE.json"
    create_correction_cycle_bundle(bundle, bundle_path)

    loaded = json.loads(bundle_path.read_text(encoding="utf-8"))
    frozen_path = tmp_path / snapshot
    frozen_bytes = frozen_path.read_bytes()
    frozen_run = json.loads(frozen_bytes)
    assert verify_correction_cycle_bundle(bundle_path, repo_root=tmp_path)["valid"] is True
    assert hashlib.sha256(frozen_bytes).hexdigest() == loaded["artifacts"][0]["sha256"]
    assert frozen_run["cycle_id"] == loaded["cycle_id"]
    assert frozen_run["head"] == loaded["head"]
    assert frozen_run["economic_verdict"] == loaded["evidence"]["verdict"]["status"]
    assert frozen_run["net_pnl_usd"] is None


def test_snapshot_refuses_to_overwrite_an_existing_content_address(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("original bytes\n", encoding="utf-8")
    snapshot = snapshot_correction_cycle_artifacts(
        repo_root=tmp_path, artifact_paths=["source.txt"], snapshot_dir="runtime/snapshots",
    )[0]
    snapshot_path = tmp_path / snapshot["snapshot_path"]
    snapshot_path.write_text("tampered bytes\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="immutable artifact snapshot already differs"):
        snapshot_correction_cycle_artifacts(
            repo_root=tmp_path, artifact_paths=["source.txt"], snapshot_dir="runtime/snapshots",
        )
    assert snapshot_path.read_text(encoding="utf-8") == "tampered bytes\n"


def test_bundle_can_verify_fixture_restoration_receipt_without_claiming_live_restore(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.fixture"
    restored = tmp_path / "restored.fixture"
    source.write_bytes(b"fixture-only bytes\n")
    shutil.copyfile(source, restored)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    restored_hash = hashlib.sha256(restored.read_bytes()).hexdigest()
    assert source_hash == restored_hash

    receipt = tmp_path / "restore-receipt.json"
    receipt.write_text(json.dumps({
        "fixture_only": True,
        "source_sha256": source_hash,
        "restored_sha256": restored_hash,
        "byte_equal": source.read_bytes() == restored.read_bytes(),
    }, sort_keys=True), encoding="utf-8")
    snapshot = snapshot_correction_cycle_artifacts(
        repo_root=tmp_path,
        artifact_paths=["restore-receipt.json"],
        snapshot_dir="runtime/cycles/restore-fixture/artifacts",
    )[0]["snapshot_path"]
    evidence = _evidence()
    evidence["restoration"] = {
        "status": "VERIFIED",
        "details": "Fixture-only byte restoration receipt; no SAFE corpus was restored.",
        "artifact_refs": [snapshot],
    }
    bundle = build_correction_cycle_bundle(
        cycle_id="restore-fixture", head=HEAD, evidence=evidence,
        artifact_paths=[snapshot], repo_root=tmp_path,
    )
    bundle_path = tmp_path / "runtime/cycles/restore-fixture/EVIDENCE.json"
    create_correction_cycle_bundle(bundle, bundle_path)

    assert verify_correction_cycle_bundle(bundle_path, repo_root=tmp_path)["valid"] is True
    assert bundle["evidence"]["restoration"]["status"] == "VERIFIED"


def test_verifier_rejects_malformed_status_values(tmp_path: Path) -> None:
    bundle = build_correction_cycle_bundle(
        cycle_id="cycle-1", head=HEAD, evidence=_evidence(), repo_root=tmp_path,
    )
    bundle["evidence"]["costs"]["status"] = ["UNVERIFIED"]
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    receipt = tmp_path / "malformed-status.json"
    receipt.write_text(json.dumps(bundle), encoding="utf-8")

    verification = verify_correction_cycle_bundle(receipt, repo_root=tmp_path)
    assert verification["valid"] is False
    assert "invalid status" in verification["bundle_error"]


def test_verifier_rejects_non_string_schema_values(tmp_path: Path) -> None:
    receipt = tmp_path / "bad-schema.json"
    receipt.write_text('{"schema":[],"bundle_sha256":"x"}', encoding="utf-8")

    verification = verify_correction_cycle_bundle(receipt, repo_root=tmp_path)
    assert verification["valid"] is False
    assert verification["bundle_error"] == "unsupported evidence bundle schema"


def test_verifier_keeps_legacy_v1_bundle_contract_readable(tmp_path: Path) -> None:
    artifact = tmp_path / "legacy-result.txt"
    artifact.write_text("legacy evidence\n", encoding="utf-8")
    bundle = build_correction_cycle_bundle(
        cycle_id="legacy-cycle", head=HEAD, evidence=_evidence(),
        artifact_paths=["legacy-result.txt"], repo_root=tmp_path,
    )
    bundle["schema"] = "hypersmart.copy_vault_correction_cycle_bundle.v1"
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    receipt = tmp_path / "legacy-v1.json"
    receipt.write_text(json.dumps(bundle), encoding="utf-8")

    assert verify_correction_cycle_bundle(receipt, repo_root=tmp_path)["valid"] is True

