"""Verify exact quarantined byte receipts, catalog drift, and corruption."""
import hashlib
import io
import json
import zipfile

from tools import recover_one_quarantined_shard as recovery
from tools import verify_quarantine_recovery as audit


def sample(tmp_path, monkeypatch):
    logical = b"0123456789ABCDEF"
    f = io.BytesIO()
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("one.jsonl.gz", logical)
    outer = f.getvalue()
    row = {"dataset_id": "one", "family": "trades",
           "quality_status": "PARTIAL", "replay_compatible": False,
           "release_tag": "tag", "release_asset": "one.jsonl.gz",
           "release_container_asset": "bundle.zip",
           "release_remote_size": len(outer),
           "release_remote_digest": "sha256:" + hashlib.sha256(outer).hexdigest(),
           "bytes": len(logical), "sha256": hashlib.sha256(logical).hexdigest()}
    index = {"release_repository_default": recovery.CANONICAL, "shards": [row]}
    asset = {"id": 21, "size": len(outer),
             "digest": "sha256:" + hashlib.sha256(outer).hexdigest(),
             "browser_download_url": "https://example.invalid/test"}
    root = tmp_path / "quarantine-root"
    root.mkdir()
    monkeypatch.setattr(recovery, "_download_to_path",
                        lambda _u, path, **k:
                        (path.write_bytes(outer), hashlib.sha256(outer).hexdigest()))
    recovery.hydrate_candidate(
        recovery.candidate_from_index(index, "one"), asset, root,
        download=True, max_source_bytes=10000, catalog_index_sha256="a"*64)
    return index, root


def test_actual_byte_coverage_is_separate_from_replay(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    checked = audit.verify_quarantine(root, index, "a"*64)
    assert checked["byte_verified_non_safe_shards"] == 1
    assert checked["byte_coverage_complete"] is True
    assert checked["unresolved_without_current_byte_proof"] == 0
    assert checked["unique_source_assets_verified"] == 1
    assert checked["replay_certified"] is False
    assert checked["all_exploitable_data_restored"] is False


def test_corrupt_bytes_and_drift_fail_without_erasing_evidence(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    # A separate collector can append unrelated rows: this unchanged shard
    # remains byte verified after the index root SHA changes.
    fresh = audit.verify_quarantine(root, index, "b"*64)
    assert fresh["invalid_or_stale_receipts"] == 0
    assert fresh["byte_verified_after_unrelated_catalog_updates"] == 1
    assert fresh["replay_certified"] is False
    changed = {**index, "shards": [
        {**index["shards"][0], "release_tag": "new-source-tag"},
    ]}
    invalid = audit.verify_quarantine(root, changed, "b"*64)
    assert invalid["invalid_or_stale_receipts"] == 1
    original = next((root/"quarantine"/"source_verified_non_replay").glob("*.jsonl.gz"))
    original.write_bytes(b"tampered")
    report = audit.verify_quarantine(root, index, "a"*64)
    assert report["invalid_or_stale_receipts"] == 1
    assert report["unresolved_without_current_byte_proof"] == 1
    # Verification failure must never inflate the count of proven sources.
    assert report["unique_source_assets_checked"] == 0
    assert report["unique_source_assets_verified"] == 0
    assert original.read_bytes() == b"tampered"


def test_legacy_quarantine_receipt_does_not_bypass_changed_index(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    receipt = next((root/"quarantine"/"source_verified_non_replay").glob("*.receipt.json"))
    data = json.loads(receipt.read_text())
    data.pop("immutable_candidate_sha256")
    receipt.write_text(json.dumps(data))
    assert audit.verify_quarantine(root, index, "a"*64)["invalid_or_stale_receipts"] == 0
    fail = audit.verify_quarantine(root, index, "b"*64)
    assert fail["invalid_or_stale_receipts"] == 1
    assert "STALE_CATALOG_PROOF_MISSING_ROW_BINDING" in str(fail["invalid_reason_counts"])


def test_corrupt_outer_cache_does_not_inflate_verified_source_count(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    outer = root / "releases" / "tag" / "bundle.zip"
    original = outer.read_bytes()
    outer.write_bytes(b"unverified-asset")
    report = audit.verify_quarantine(root, index, "a" * 64)
    assert report["invalid_or_stale_receipts"] == 1
    assert report["byte_verified_non_safe_shards"] == 0
    assert report["unique_source_assets_checked"] == 1
    assert report["unique_source_assets_verified"] == 0
    assert report["replay_certified"] is False
    assert outer.read_bytes() == b"unverified-asset"


def test_quarantine_coverage_tracks_verified_bytes_by_family_without_loss_claim(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    # Include a second, independent missing book shard: absence from this
    # small isolated cache is NOT proof that its Release was lost.
    extra = {
        **index["shards"][0],
        "dataset_id": "missing-l2",
        "family": "l2book",
        "release_asset": "missing-l2.jsonl.gz",
        "sha256": "b" * 64,
    }
    mixed = {**index, "shards": [*index["shards"], extra]}
    report = audit.verify_quarantine(root, mixed, "b" * 64)
    assert report["unresolved_catalog_shards"] == 2
    assert report["byte_verified_non_safe_shards"] == 1
    assert report["unresolved_candidates_by_family"] == {"l2book": 1, "trades": 1}
    assert report["byte_verified_shards_by_family"] == {"trades": 1}
    assert report["byte_verified_compressed_bytes_by_family"] == {"trades": 16}
    assert report["candidates_without_current_byte_proof_by_family"] == {
        "l2book": 1, "trades": 0,
    }
    assert report["unknown_unverified_compressed_bytes"] is True
    assert report["all_exploitable_data_restored"] is False


def test_recovery_audit_refuses_symlinked_quarantine_parent(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    real = root / "quarantine"
    saved = tmp_path / "original-quarantine"
    real.rename(saved)
    real.symlink_to(saved, target_is_directory=True)
    with __import__("pytest").raises(audit.InventoryError, match="UNSAFE_QUARANTINE"):
        audit.verify_quarantine(root, index, "a" * 64)
    assert next(saved.rglob("*.receipt.json")).is_file()


def test_recovery_audit_rejects_receipt_alias_without_deleting(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    directory = root / "quarantine" / "source_verified_non_replay"
    proof = next(directory.glob("*.receipt.json"))
    alias = directory / "unrelated-alias.receipt.json"
    proof.rename(alias)
    report = audit.verify_quarantine(root, index, "a" * 64)
    assert report["byte_verified_non_safe_shards"] == 0
    assert report["invalid_or_stale_receipts"] == 1
    assert "RECEIPT_FILENAME_NOT_BOUND_TO_DATASET" in str(report["invalid_reason_counts"])
    assert alias.exists()


def test_recovery_audit_requires_inner_member_in_hashed_zip(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    directory = root / "quarantine" / "source_verified_non_replay"
    receipt_path = next(directory.glob("*.receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    outer = root / "releases" / "tag" / "bundle.zip"
    logical = next(directory.glob("*.jsonl.gz")).read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("not-the-catalog-member.jsonl.gz", logical)
    new_outer = output.getvalue()
    sha = hashlib.sha256(new_outer).hexdigest()
    outer.write_bytes(new_outer)
    row = index["shards"][0]
    row["release_remote_size"] = len(new_outer)
    row["release_remote_digest"] = "sha256:" + sha
    receipt["outer_bytes"] = len(new_outer)
    receipt["outer_sha256"] = sha
    receipt["immutable_candidate_sha256"] = recovery.immutable_candidate_sha256(
        recovery.candidate_from_index(index, row["dataset_id"])
    )
    receipt_path.write_text(json.dumps(receipt))
    result = audit.verify_quarantine(root, index, "b" * 64)
    assert result["byte_verified_non_safe_shards"] == 0
    assert result["invalid_or_stale_receipts"] == 1
    assert "SOURCE_ZIP_MEMBER_NOT_UNIQUE_OR_SIZE_CONFLICT" in str(result["invalid_reason_counts"])
    assert next(directory.glob("*.jsonl.gz")).read_bytes() == logical


def test_legacy_receipt_must_not_certify_foreign_repository(tmp_path, monkeypatch):
    index, root = sample(tmp_path, monkeypatch)
    receipt_path = next(
        (root / "quarantine" / "source_verified_non_replay").glob("*.receipt.json")
    )
    original = receipt_path.read_bytes()
    receipt = json.loads(original)
    receipt.pop("immutable_candidate_sha256")
    receipt_path.write_text(json.dumps(receipt))
    foreign = {**index, "shards": [
        {**index["shards"][0], "release_repository": "other-owner/other-repo"}
    ]}
    result = audit.verify_quarantine(root, foreign, "a" * 64)
    assert result["byte_verified_non_safe_shards"] == 0
    assert result["invalid_or_stale_receipts"] == 1
    assert "CATALOG_SOURCE_REPOSITORY_NOT_CANONICAL" in str(result["invalid_reason_counts"])
    assert (root / "releases" / "tag" / "bundle.zip").is_file()
    assert receipt_path.is_file()
