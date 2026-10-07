from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "restore_alina_test", ROOT / "tools" / "restore_alina.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _asset(name: str, url: str, payload: bytes) -> dict:
    return {
        "name": name,
        "browser_download_url": url,
        "size": len(payload),
        "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


def test_restore_everything_downloads_and_verifies_run_manifest(tmp_path, monkeypatch):
    module = _module()
    shard = b'{"trade_id":"abc","px":"100"}\n'
    shard_sha = hashlib.sha256(shard).hexdigest()
    manifest = {
        "schema": "alina.dataset_run_manifest.v2",
        "release_tag": "data-v2-test",
        "data_release_base_tag": "data-v2-test",
        "manifests": [
            {
                "dataset_id": "test-trades",
                "release_tag": "data-v2-test",
                "release_asset": "trades.jsonl.gz",
                "sha256": shard_sha,
            }
        ],
    }
    manifest_bytes = json.dumps(manifest).encode("utf-8")
    payloads = {
        "https://example.invalid/trades": shard,
        "https://example.invalid/manifest": manifest_bytes,
    }
    releases = [
        {
            "tag_name": "data-v2-test",
            "assets": [
                _asset("trades.jsonl.gz", "https://example.invalid/trades", shard),
                _asset(
                    "RUN_MANIFEST.json",
                    "https://example.invalid/manifest",
                    manifest_bytes,
                ),
            ],
        }
    ]

    monkeypatch.setattr(module, "iter_releases", lambda *_args, **_kwargs: iter(releases))
    monkeypatch.setattr(
        module,
        "_request",
        lambda url, **_kwargs: payloads[url],
    )

    report = module.restore_everything("owner/repo", tmp_path)

    assert report["release_count"] == 1
    assert report["asset_count"] == 2
    assert report["downloaded"] == 2
    assert report["failures"] == []
    assert report["verification_failures"] == 0
    assert report["run_manifest_checks"][0]["status"] == "OK"
    assert (tmp_path / "releases" / "data-v2-test" / "trades.jsonl.gz").read_bytes() == shard


def test_download_asset_rejects_digest_mismatch(tmp_path, monkeypatch):
    module = _module()
    good = b"expected"
    bad = b"corrupted"
    asset = _asset("asset.bin", "https://example.invalid/asset", good)
    monkeypatch.setattr(module, "_request", lambda *_args, **_kwargs: bad)

    try:
        module.download_asset(asset, tmp_path)
    except module.RestoreError as exc:
        assert "size mismatch" in str(exc) or "sha256 mismatch" in str(exc)
    else:
        raise AssertionError("corrupted restore asset must fail closed")


def test_materialize_latest_local_snapshot_rebuilds_large_runtime_file(tmp_path):
    module = _module()
    releases_root = tmp_path / "downloads" / "releases"
    release = releases_root / "alina-local-snapshot-20261007T200000Z"
    release.mkdir(parents=True)
    payload = b"abc123" * 100
    chunk = release / "ALINA_LOCAL_SNAPSHOT.chunk0000.bin"
    chunk.write_bytes(payload)
    target_bytes = payload[10:210] + payload[300:450]
    index = {
        "schema": "alina.local_snapshot.v1",
        "tag": release.name,
        "chunks": [
            {
                "name": chunk.name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
        "files": [
            {
                "path": "runtime/replay/example.bin",
                "bytes": len(target_bytes),
                "sha256": hashlib.sha256(target_bytes).hexdigest(),
                "segments": [
                    {"chunk": chunk.name, "offset": 10, "bytes": 200},
                    {"chunk": chunk.name, "offset": 300, "bytes": 150},
                ],
            }
        ],
    }
    (release / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps(index), encoding="utf-8"
    )
    workspace = tmp_path / "fresh-clone"
    workspace.mkdir()

    result = module.materialize_latest_local_snapshot(releases_root, workspace)

    assert result is not None
    assert result["restored_files"] == 1
    assert (workspace / "runtime" / "replay" / "example.bin").read_bytes() == target_bytes
