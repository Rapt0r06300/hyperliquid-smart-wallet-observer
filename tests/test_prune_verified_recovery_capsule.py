"""Deterministic tests: a recovery capsule is disposable ONLY with exact SAFE parity."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import tarfile

import pytest

from tools import prune_verified_recovery_capsule as gc


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def remote(name, payload):
    return {
        "name": name, "size": len(payload), "digest": "sha256:" + digest(payload),
        "state": "uploaded",
        "browser_download_url": (
            f"https://github.com/{gc.REPOSITORY}/releases/download/test/{name}"
        ),
    }


def fixture(monkeypatch, *, source_payload=b'{"trade":1}\n'):
    name = "safe.jsonl.gz"
    source_manifest = {
        "dataset_id": "safe-1", "release_asset": name,
        "sha256": digest(b'{"trade":1}\n'),
        "bytes": len(b'{"trade":1}\n'),
        "quality_status": "PARTIAL",
        "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
    }
    final = {
        **source_manifest, "quality_status": "SAFE",
        "quality_reasons": [], "replay_compatible": True, "asset_verified": True,
        "release": {
            "repository": gc.REPOSITORY,
            "release_tag": "data-v2-test",
            "asset_name": name,
            "remote_size": len(b'{"trade":1}\n'),
            "remote_digest": "sha256:" + digest(b'{"trade":1}\n'),
        },
    }
    run = {
        "repository": gc.REPOSITORY, "release_tag": "data-v2-test",
        "recovery_capsule": {"release_tag": "alina-recovery-test"},
        "shard_count": 1, "safe_count": 1, "partial_count": 0,
        "reject_count": 0, "manifests": [final],
    }
    run_bytes = json.dumps(run).encode()
    bundle_index = {
        "manifests": ["manifests/safe.json"],
        "assets": ["assets/" + name],
    }
    bundle_bytes = json.dumps(bundle_index).encode()
    tarstream = io.BytesIO()
    with tarfile.open(fileobj=tarstream, mode="w") as tar:
        for filename, data in [
            ("BUNDLE_INDEX.json", bundle_bytes),
            ("manifests/safe.json", json.dumps(source_manifest).encode()),
            ("assets/" + name, source_payload),
        ]:
            info = tarfile.TarInfo(filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    tarbytes = tarstream.getvalue()
    index_bytes = json.dumps({
        "schema": "alina.recovery_capsule.v1", "repository": gc.REPOSITORY,
        "bundle_index_sha256": digest(bundle_bytes),
        "parts": [{
            "name": "ALINA_RECOVERY_BUNDLE.part000.tar",
            "bytes": len(tarbytes), "sha256": digest(tarbytes),
        }],
    }).encode()
    complete_bytes = json.dumps({
        "schema": "alina.recovery_capsule_completion.v1",
        "repository": gc.REPOSITORY,
        "recovery_release_tag": "alina-recovery-test",
        "canonical_release_tag": "data-v2-test",
        "run_manifest_sha256": digest(run_bytes),
        "run_manifest_bytes": len(run_bytes),
    }).encode()
    blobs = {
        "ALINA_RECOVERY_BUNDLE.part000.tar": tarbytes,
        "ALINA_RECOVERY_INDEX.json": index_bytes,
        "CANONICAL_PUBLICATION.json": complete_bytes,
        "RUN_MANIFEST.json": run_bytes,
        name: b'{"trade":1}\n',
    }
    releases = {
        "alina-recovery-test": {
            "id": 123, "tag_name": "alina-recovery-test",
            "assets": [remote(k, blobs[k]) for k in (
                "ALINA_RECOVERY_BUNDLE.part000.tar",
                "ALINA_RECOVERY_INDEX.json", "CANONICAL_PUBLICATION.json"
            )],
        },
        "data-v2-test": {
            "id": 124, "tag_name": "data-v2-test",
            "assets": [remote(k, blobs[k]) for k in (
                "RUN_MANIFEST.json", name
            )],
        },
    }

    def fake_download(asset, target, *, max_bytes):
        data = blobs[asset["name"]]
        assert len(data) <= max_bytes
        assert digest(data) == asset["digest"].removeprefix("sha256:")
        target.write_bytes(data)
        return digest(data)

    monkeypatch.setattr(gc, "release", lambda tag: copy.deepcopy(releases[tag]))
    monkeypatch.setattr(gc, "download", fake_download)
    return releases, blobs


def test_proves_all_capsule_payload_bytes_equal_published_safe(monkeypatch):
    fixture(monkeypatch)
    receipt = gc.verify_capsule("alina-recovery-test", max_bytes=1024**3)
    assert receipt["status"] == "REDUNDANT_CAPSULE_BYTES_VERIFIED"
    assert receipt["safe_shards_verified"] == 1
    assert receipt["recovery_release_id"] == 123
    assert receipt["recovery_bytes_verified"] > 0


def test_refuses_when_source_payload_differs_from_canonical(monkeypatch):
    fixture(monkeypatch, source_payload=b'{"trade":2}\n')
    with pytest.raises(gc.Refuse, match="CAPSULE_MEMBER_NOT_EQUAL_TO_CANONICAL"):
        gc.verify_capsule("alina-recovery-test", max_bytes=1024**3)


def test_refuses_missing_remote_canonical_completion(monkeypatch):
    releases, _ = fixture(monkeypatch)
    releases["alina-recovery-test"]["assets"] = [
        item for item in releases["alina-recovery-test"]["assets"]
        if item["name"] != "CANONICAL_PUBLICATION.json"
    ]
    with pytest.raises(gc.Refuse, match="NO_CANONICAL_COMPLETION_PROOF"):
        gc.verify_capsule("alina-recovery-test", max_bytes=1024**3)


def test_execution_requires_explicit_frozen_identity(monkeypatch):
    fixture(monkeypatch)
    monkeypatch.setenv("GH_TOKEN", "not-used")
    monkeypatch.setattr(
        gc, "request", lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("release DELETE was attempted without matching lease")
        ),
    )
    monkeypatch.setattr("sys.argv", [
        "gc", "--recovery-tag", "alina-recovery-test", "--execute",
        "--expected-release-id", "999",
        "--expected-canonical-sha256", "0" * 64,
    ])
    assert gc.main() == 2
