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
