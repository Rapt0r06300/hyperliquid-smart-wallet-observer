from __future__ import annotations

import gzip
import hashlib
import json

import pytest
from tools.unpack_verified_safe import SafeUnpackError, expand_safe_corpus


def fixture(root):
    path = root / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(b'{"px":100}\n', mtime=0))
    _bind_catalog(root, path, "safe")


def _digest(root):
    return hashlib.sha256((root / "catalog" / "DATA_INDEX.json").read_bytes()).hexdigest()


def _bind_catalog(root, source, dataset_id):
    index = root / "catalog" / "DATA_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({
        "schema": "alina.data_index.v2",
        "shards": [{
            "dataset_id": dataset_id,
            "release_tag": source.parent.name,
            "release_asset": source.name,
            "quality_status": "SAFE",
            "replay_compatible": True,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "bytes": source.stat().st_size,
        }],
    }), encoding="utf-8")
    (root / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "classification": {"materialization_complete": True, "usable_shards": 1},
        "catalog_verification": {"source_index_sha256": _digest(root)},
    }), encoding="utf-8")


def _expand(root, *, catalog_sha256=None):
    return expand_safe_corpus(
        root,
        catalog_sha256=catalog_sha256 if catalog_sha256 is not None else _digest(root),
        catalog_path=root / "catalog" / "DATA_INDEX.json",
    )


def test_unpacked_safe_is_verified_and_resumable(tmp_path):
    fixture(tmp_path)
    report = _expand(tmp_path)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    assert report["status"] == "SAFE_UNPACK_COMPLETE"
    assert target.read_bytes() == b'{"px":100}\n'
    assert _expand(tmp_path)["reused_verified"] == 1
    seal = json.loads(target.with_suffix(".jsonl.alina.json").read_text())
    assert seal["jsonl_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_tampered_unpacked_shard_fails_closed(tmp_path):
    fixture(tmp_path)
    with pytest.raises(SafeUnpackError, match="not certified"):
        _expand(tmp_path, catalog_sha256="b" * 64)
    _expand(tmp_path)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    target.write_text("corrupt\n", encoding="utf-8")
    with pytest.raises(SafeUnpackError, match="changed"):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"


def test_bad_gzip_does_not_produce_complete_report(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    damaged = bytearray(path.read_bytes())
    damaged[-8] ^= 17
    path.write_bytes(damaged)
    with pytest.raises((SafeUnpackError, gzip.BadGzipFile, OSError)):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"


def test_unpack_flag_requires_explicit_safe_download():
    from tools.sync_complete_clone import main
    assert main(["--unpack-safe"]) == 2


def test_unselected_prior_jsonl_is_quarantined_not_mixed_or_deleted(tmp_path):
    fixture(tmp_path)
    _expand(tmp_path)
    old = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    source = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    source.unlink()
    new = source.parent / "new.jsonl.gz"
    new.write_bytes(gzip.compress(b'{"px":200}\n', mtime=0))
    _bind_catalog(tmp_path, new, "new")
    outcome = _expand(tmp_path)
    assert outcome["quarantined_stale_outputs"] == 1
    assert not old.exists()
    assert list((tmp_path / "quarantine" / "stale_unpacked").rglob("*.stale"))
    assert (tmp_path / "usable" / "unpacked" / "release-one" / "new.jsonl").is_file()


def test_valid_gzip_with_invalid_jsonl_is_rejected(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    path.write_bytes(gzip.compress(b"this-is-not-json\n", mtime=0))
    _bind_catalog(tmp_path, path, "safe")
    with pytest.raises(SafeUnpackError, match="invalid JSONL"):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"
    assert not (tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl").exists()



def test_interrupted_unsealed_jsonl_quarantined_and_reconstructed(tmp_path):
    fixture(tmp_path)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"partial crash output")
    result = _expand(tmp_path)
    assert result["status"] == "SAFE_UNPACK_COMPLETE"
    assert result["quarantined_unsealed_outputs"] == 1
    assert target.read_bytes() == b'{"px":100}\n'
    assert list((tmp_path / "quarantine" / "unsealed_unpacked").rglob("*.unsealed"))


def test_modified_but_valid_gzip_must_not_be_accepted_as_certified_safe(tmp_path):
    fixture(tmp_path)
    source = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    source.write_bytes(gzip.compress(b'{"px":999}\n', mtime=0))
    with pytest.raises(SafeUnpackError, match="SHA-256 changed"):
        _expand(tmp_path)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"
