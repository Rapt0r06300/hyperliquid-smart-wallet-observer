"""A chosen non-SAFE shard is restored only to immutable-byte quarantine."""
import hashlib
import io
import zipfile

import pytest

from tools import recover_one_quarantined_shard as recovery


def fixture(tmp_path):
    logical = b"\x1f\x8b" + b"A" * 13
    f = io.BytesIO()
    with zipfile.ZipFile(f, "w") as archive:
        archive.writestr("trades.jsonl.gz", logical)
    outer = f.getvalue()
    row = {
        "dataset_id": "one", "quality_status": "PARTIAL",
        "replay_compatible": False, "release_tag": "unit-tag",
        "release_asset": "trades.jsonl.gz",
        "release_container_asset": "one.zip",
        "release_remote_size": len(outer),
        "release_remote_digest": "sha256:" + hashlib.sha256(outer).hexdigest(),
        "bytes": len(logical), "sha256": hashlib.sha256(logical).hexdigest(),
    }
    index = {"release_repository_default": recovery.CANONICAL, "shards": [row]}
    candidate = recovery.candidate_from_index(index, "one")
    asset = {"id": 42, "size": len(outer), "digest": "sha256:" + candidate["outer_sha256"],
             "browser_download_url": "https://github.com/fake/release"}
    destination = tmp_path / "recovery"
    destination.mkdir()
    return index, candidate, asset, outer, logical, destination


def test_preflight_is_non_mutating_and_quarantine_bytes_verified(tmp_path, monkeypatch):
    index, candidate, asset, outer, logical, root = fixture(tmp_path)
    pre = recovery.hydrate_candidate(candidate, asset, root, download=False)
    assert pre["status"] == "LIVE_ASSET_IDENTIFIED_NOT_DOWNLOADED"
    assert not list(root.iterdir())
    def download(_url, target, **_kw):
        target.write_bytes(outer)
        return len(outer), hashlib.sha256(outer).hexdigest()
    monkeypatch.setattr(recovery, "_download_to_path", download)
    result = recovery.hydrate_candidate(candidate, asset, root,
                                        download=True, catalog_index_sha256="e" * 64, max_source_bytes=10000)
    assert result["status"] == "BYTE_VERIFIED_QUARANTINED_NOT_REPLAY_CERTIFIED"
    assert result["replay_certified"] is False
    assert result["validation_allowed"] is False
    assert (root / result["quarantine_file"]).read_bytes() == logical
    assert recovery.hydrate_candidate(candidate, asset, root,
                                      download=True, catalog_index_sha256="e" * 64, max_source_bytes=10000)["source_cached_before_run"] is True
    assert not (root / "usable").exists()


def test_hash_mismatch_and_size_budget_fail_without_reclassification(tmp_path, monkeypatch):
    index, candidate, asset, outer, logical, root = fixture(tmp_path)
    with pytest.raises(ValueError, match="SIZE_BUDGET"):
        recovery.hydrate_candidate(candidate, asset, root, download=True, catalog_index_sha256="e" * 64, max_source_bytes=1)
    def corrupt(_url, target, **_kw):
        target.write_bytes(b"corrupt")
        return 7, hashlib.sha256(b"corrupt").hexdigest()
    monkeypatch.setattr(recovery, "_download_to_path", corrupt)
    with pytest.raises(ValueError, match="REMOTE_BYTES_MISMATCH"):
        recovery.hydrate_candidate(candidate, asset, root, download=True, catalog_index_sha256="e" * 64)
    assert not list((root / "quarantine" / "source_verified_non_replay").iterdir())
    assert not (root / "usable").exists()


def test_no_automatic_safe_replay_reclassification(tmp_path):
    index, _, _, _, _, _ = fixture(tmp_path)
    index["shards"][0]["quality_status"] = "SAFE"
    index["shards"][0]["replay_compatible"] = True
    with pytest.raises(ValueError, match="ALREADY_REPLAY_READY"):
        recovery.candidate_from_index(index, "one")
    index["shards"][0]["quality_status"] = "REJECT"
    assert recovery.candidate_from_index(index, "one")["quality_status"] == "REJECT"
    index["shards"][0]["release_repository"] = "foreign/repo"
    with pytest.raises(ValueError, match="NOT_CANONICAL"):
        recovery.candidate_from_index(index, "one")



def test_preexisting_unverified_target_is_preserved_and_blocks_recovery(tmp_path, monkeypatch):
    _index, candidate, asset, outer, _logical, root = fixture(tmp_path)
    directory = root / "releases" / "unit-tag"
    directory.mkdir(parents=True)
    (directory / "one.zip").write_bytes(b"never-overwrite")
    monkeypatch.setattr(recovery, "_download_to_path",
                        lambda *_a, **_kw: pytest.fail("download must not run"))
    with pytest.raises(ValueError, match="EXISTING_OUTER_CONFLICT"):
        recovery.hydrate_candidate(candidate, asset, root, download=True, catalog_index_sha256="e" * 64)
    assert (directory / "one.zip").read_bytes() == b"never-overwrite"



def test_github_hosted_manual_recovery_is_one_shard_paper_and_bounded():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / ".github"
                / "workflows" / "catalog-partition-parity.yml").read_text()
    assert "hydrate_candidate_id:" in workflow
    assert "recover-one:" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "inputs.hydrate_candidate_id != ''" in workflow
    assert "--dataset-id" in workflow
    assert "--max-source-bytes 100000000" in workflow
    assert "--download" in workflow
    assert "BYTE_VERIFIED_QUARANTINED_NOT_REPLAY_CERTIFIED" in workflow
    assert "assert report[\"validation_allowed\"] is False" in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "contents: read" in workflow
    assert "self-hosted" not in workflow



def test_restorer_network_stream_enforces_byte_cap_before_writing(tmp_path, monkeypatch):
    from tools import restore_alina
    import hashlib

    class Response:
        status = 200
        headers = {}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self, _n):
            if not hasattr(self, "sent"):
                self.sent = True
                return b"untrusted-bytes"
            return b""

    monkeypatch.setattr(restore_alina.urllib.request, "urlopen",
                        lambda *_a, **_kw: Response())
    path = tmp_path / "limited.partial"
    with pytest.raises(restore_alina.RestoreError, match="bounded byte limit"):
        restore_alina._download_to_path("https://example.invalid/asset", path,
                                       max_bytes=4)
    assert path.read_bytes() == b""
    size, digest = restore_alina._download_to_path(
        "https://example.invalid/asset", path, max_bytes=100)
    assert size == len(b"untrusted-bytes")
    assert digest == hashlib.sha256(b"untrusted-bytes").hexdigest()



def test_quarantine_receipt_has_canonical_catalog_and_live_release_asset_id(tmp_path, monkeypatch):
    import json
    _idx, candidate, asset, outer, _inner, root = fixture(tmp_path)
    monkeypatch.setattr(recovery, "_download_to_path",
                        lambda _url, path, **kw:
                        (path.write_bytes(outer), hashlib.sha256(outer).hexdigest()))
    result = recovery.hydrate_candidate(
        candidate, asset, root, download=True, max_source_bytes=10000,
        catalog_index_sha256="e" * 64)
    file = root / "quarantine" / "source_verified_non_replay"
    receipts = list(file.glob("*.receipt.json"))
    assert len(receipts) == 1
    stored = json.loads(receipts[0].read_text())
    assert stored["catalog_index_sha256"] == "e" * 64
    assert stored["source_asset_id"] == 42
    assert stored["source_repository"] == recovery.CANONICAL
    assert stored["validation_allowed"] is False
    assert result["catalog_index_sha256"] == stored["catalog_index_sha256"]


def test_recovery_pilot_chooses_verified_small_non_safe_without_download(monkeypatch, tmp_path):
    index, _candidate, _asset, _outer, _logical, _root = fixture(tmp_path)
    row = index["shards"][0]
    row.update(family="bbo", start_ts_ms=1, quality_status="PARTIAL")
    index["shards"].append(dict(row, dataset_id="safe", quality_status="SAFE", replay_compatible=True))
    monkeypatch.setattr(recovery, "live_asset", lambda candidate, **kw: {
        "id": 8, "size": candidate["outer_bytes"]})
    selected = recovery.select_pilot_candidate(
        index, max_source_bytes=10_000, max_live_attempts=2)
    assert selected["dataset_id"] == "one"
    assert selected["source_asset_id"] == 8
    assert selected["replay_certified"] is False


def test_recovery_pilot_refuses_unbounded_or_unverifiable_sources(monkeypatch, tmp_path):
    index, _candidate, _asset, _outer, _logical, _root = fixture(tmp_path)
    with pytest.raises(ValueError, match="INVALID_BOUNDS"):
        recovery.select_pilot_candidate(index, max_source_bytes=0)
    monkeypatch.setattr(recovery, "live_asset",
                        lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("offline")))
    with pytest.raises(ValueError, match="NO_VERIFIABLE_LIVE_SOURCE"):
        recovery.select_pilot_candidate(index, max_source_bytes=1_000_000)


def test_hosted_auto_pilot_only_on_explicit_pilot_commit():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1]
                / ".github" / "workflows" / "catalog-partition-parity.yml").read_text()
    assert "startsWith(github.event.head_commit.message, 'recovery-pilot:')" in workflow
    assert "--select-pilot" in workflow
    assert "--max-live-attempts 12" in workflow
    assert "LIMIT=4000000" in workflow
    assert "SELECTED_DATASET_ID=$SELECTED_DATASET_ID" in workflow
    assert "--download > \"$OUTPUT/RECOVERY_RESULT.json\"" in workflow
    assert "CONTENT_REPLAY_CHECK_PASSED_NOT_SAFE" in workflow
    assert "alina-selected-quarantined-shard-" in workflow
    assert workflow.count("runs-on: ubuntu-latest") >= 2
