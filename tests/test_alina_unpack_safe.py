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
    (root / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "classification": {"materialization_complete": True, "usable_shards": 1},
        "catalog_verification": {"source_index_sha256": "a" * 64},
    }), encoding="utf-8")


def test_unpacked_safe_is_verified_and_resumable(tmp_path):
    fixture(tmp_path)
    report = expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    assert report["status"] == "SAFE_UNPACK_COMPLETE"
    assert target.read_bytes() == b'{"px":100}\n'
    assert expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)["reused_verified"] == 1
    seal = json.loads(target.with_suffix(".jsonl.alina.json").read_text())
    assert seal["jsonl_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_tampered_unpacked_shard_fails_closed(tmp_path):
    fixture(tmp_path)
    with pytest.raises(SafeUnpackError, match="not certified"):
        expand_safe_corpus(tmp_path, catalog_sha256="b" * 64)
    expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    target.write_text("corrupt\n", encoding="utf-8")
    with pytest.raises(SafeUnpackError, match="changed"):
        expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"


def test_bad_gzip_does_not_produce_complete_report(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    damaged = bytearray(path.read_bytes())
    damaged[-8] ^= 17
    path.write_bytes(damaged)
    with pytest.raises((SafeUnpackError, gzip.BadGzipFile, OSError)):
        expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"


def test_unpack_flag_requires_explicit_safe_download():
    from tools.sync_complete_clone import main
    assert main(["--unpack-safe"]) == 2


def test_unselected_prior_jsonl_is_quarantined_not_mixed_or_deleted(tmp_path):
    fixture(tmp_path)
    expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    old = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    source = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    source.unlink()
    new = source.parent / "new.jsonl.gz"
    new.write_bytes(gzip.compress(b'{"px":200}\n', mtime=0))
    outcome = expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    assert outcome["quarantined_stale_outputs"] == 1
    assert not old.exists()
    assert list((tmp_path / "quarantine" / "stale_unpacked").rglob("*.stale"))
    assert (tmp_path / "usable" / "unpacked" / "release-one" / "new.jsonl").is_file()


def test_valid_gzip_with_invalid_jsonl_is_rejected(tmp_path):
    fixture(tmp_path)
    path = tmp_path / "usable" / "shards" / "release-one" / "safe.jsonl.gz"
    path.write_bytes(gzip.compress(b"this-is-not-json\n", mtime=0))
    with pytest.raises(SafeUnpackError, match="invalid JSONL"):
        expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    assert json.loads((tmp_path / "UNPACK_REPORT.json").read_text())["status"] != "SAFE_UNPACK_COMPLETE"
    assert not (tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl").exists()



def test_interrupted_unsealed_jsonl_quarantined_and_reconstructed(tmp_path):
    fixture(tmp_path)
    target = tmp_path / "usable" / "unpacked" / "release-one" / "safe.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"partial crash output")
    result = expand_safe_corpus(tmp_path, catalog_sha256="a" * 64)
    assert result["status"] == "SAFE_UNPACK_COMPLETE"
    assert result["quarantined_unsealed_outputs"] == 1
    assert target.read_bytes() == b'{"px":100}\n'
    assert list((tmp_path / "quarantine" / "unsealed_unpacked").rglob("*.unsealed"))
