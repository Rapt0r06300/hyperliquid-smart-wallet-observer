from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools import verify_safe_corpus_partition as verifier
from tools.restore_alina import RestoreError


def _row(dataset_id: str, member: str, payload: bytes, *, zipped: bool = True) -> dict:
    row = {
        "dataset_id": dataset_id,
        "release_tag": "release-1",
        "release_asset": member,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if zipped:
        row["release_container_asset"] = "bundle.zip"
    return row


def _specs() -> list[dict]:
    rows = [
        _row("dataset-a", "a.jsonl.gz", b"alpha"),
        _row("dataset-b", "b.jsonl.gz", b"bravo"),
    ]
    return verifier.build_outer_specs(
        rows,
        {("release-1", "bundle.zip"): (11, "a" * 64)},
    )


def test_partition_assignment_is_deterministic_and_byte_balanced() -> None:
    specs = [
        {"release_tag": "r", "asset_name": f"a-{index}", "asset_bytes": size}
        for index, size in enumerate((9, 8, 7, 6, 5, 4))
    ]
    first = verifier.assign_partitions(specs, 3)
    second = verifier.assign_partitions(reversed(specs), 3)
    assert [[row["asset_name"] for row in bucket] for bucket in first] == [
        [row["asset_name"] for row in bucket] for bucket in second
    ]
    assert sorted(sum(int(row["asset_bytes"]) for row in bucket) for bucket in first) == [13, 13, 13]


def test_verify_file_checks_every_selected_zip_member(tmp_path: Path) -> None:
    spec = _specs()[0]
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("a.jsonl.gz", b"alpha")
        handle.writestr("b.jsonl.gz", b"bravo")
        handle.writestr("unselected.bin", b"not part of SAFE")

    result = verifier._verify_file(archive, spec)
    assert result["status"] == "OUTER_AND_SELECTED_MEMBERS_SHA256_VERIFIED"
    assert result["unique_members_verified"] == 2
    assert result["member_rows"] == 2


def test_verify_file_rejects_tampered_selected_member(tmp_path: Path) -> None:
    spec = _specs()[0]
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("a.jsonl.gz", b"alpha")
        handle.writestr("b.jsonl.gz", b"wrong")
    with pytest.raises(RestoreError, match="SHA-256 mismatch"):
        verifier._verify_file(archive, spec)


def test_aggregate_requires_exact_duplicate_free_partition_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = _specs()
    monkeypatch.setattr(
        verifier,
        "_load_specs",
        lambda _index, _metrics: ({"source_index_sha256": "c" * 64}, specs),
    )
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    summary = verifier._asset_summary(specs[0])
    payload = {
        "schema": verifier.SCHEMA,
        "status": "PARTITION_FULLY_BYTE_VERIFIED",
        "repository": verifier.REPOSITORY,
        "git_sha": "d" * 40,
        "catalog_sha256": "c" * 64,
        "partition": 0,
        "partition_count": 1,
        "verified": [{**summary, "status": "OUTER_AND_SELECTED_MEMBERS_SHA256_VERIFIED"}],
    }
    (receipts / "safe-corpus-partition-0.json").write_text(json.dumps(payload))
    output = tmp_path / "certificate.json"
    result = verifier.aggregate(
        index=Path("index"), metrics=Path("metrics"), partitions=1,
        receipts=receipts, output=output, git_sha="d" * 40,
    )
    assert result["status"] == "DISTRIBUTED_SAFE_CORPUS_BYTES_FULLY_VERIFIED"
    assert result["verified_outer_assets"] == 1
    assert result["single_machine_full_restore"] is False

    payload["verified"].append(payload["verified"][0])
    (receipts / "safe-corpus-partition-0.json").write_text(json.dumps(payload))
    with pytest.raises(RestoreError, match="duplicate or mismatched"):
        verifier.aggregate(
            index=Path("index"), metrics=Path("metrics"), partitions=1,
            receipts=receipts, output=output, git_sha="d" * 40,
        )

def test_aggregate_rejects_forged_partition_and_removes_stale_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = _specs()
    monkeypatch.setattr(
        verifier, "_load_specs",
        lambda _index, _metrics: ({"source_index_sha256": "c" * 64}, specs),
    )
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    output = tmp_path / "certificate.json"
    output.write_text('{"status":"DISTRIBUTED_SAFE_CORPUS_BYTES_FULLY_VERIFIED"}')
    payload = {
        "schema": verifier.SCHEMA,
        "status": "PARTITION_FULLY_BYTE_VERIFIED",
        "repository": verifier.REPOSITORY,
        "git_sha": "d" * 40,
        "catalog_sha256": "c" * 64,
        "partition": 2,
        "partition_count": 1,
        "verified": [],
    }
    receipt = receipts / "safe-corpus-partition-0.json"
    receipt.write_text(json.dumps(payload))
    with pytest.raises(RestoreError, match="invalid partition receipt"):
        verifier.aggregate(
            index=Path("index"), metrics=Path("metrics"), partitions=1,
            receipts=receipts, output=output, git_sha="d" * 40,
        )
    assert not output.exists()

    payload["partition"] = 0
    payload["verified"] = [{
        **verifier._asset_summary(specs[0]),
        "asset_name": "unknown-forged-asset.zip",
    }]
    receipt.write_text(json.dumps(payload))
    with pytest.raises(RestoreError, match="duplicate or mismatched"):
        verifier.aggregate(
            index=Path("index"), metrics=Path("metrics"), partitions=1,
            receipts=receipts, output=output, git_sha="d" * 40,
        )
    assert not output.exists()
