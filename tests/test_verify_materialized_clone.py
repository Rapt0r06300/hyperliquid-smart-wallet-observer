from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "verify_materialized_clone_test",
        ROOT / "tools" / "verify_materialized_clone.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_manifest(root: Path, *, payload: bytes, path: str) -> None:
    manifest_path = root / "clone_payload" / "MANIFEST.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "alina.clone_payload_manifest.v1",
                "entries": [
                    {
                        "asset_id": 1,
                        "clone_path": path,
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
                "total_assets": 1,
                "total_bytes": len(payload),
            }
        ),
        encoding="utf-8",
    )


def test_verify_materialized_clone_exact_bytes(tmp_path):
    module = _module()
    payload = b"real-lfs-payload-bytes"
    relative = "clone_payload/releases/test/1--asset.bin"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)
    _write_manifest(tmp_path, payload=payload, path=relative)

    report = module.verify(tmp_path)

    assert report["complete"] is True
    assert report["verified_assets"] == 1
    assert report["verified_bytes"] == len(payload)
    assert report["failure_count"] == 0


def test_verify_materialized_clone_rejects_lfs_pointer(tmp_path):
    module = _module()
    sha = "a" * 64
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{sha}\n"
        "size 999\n"
    ).encode()
    relative = "clone_payload/releases/test/1--asset.bin"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(pointer)
    _write_manifest(tmp_path, payload=b"x" * 999, path=relative)

    report = module.verify(tmp_path)

    assert report["complete"] is False
    assert report["failure_count"] == 1
    assert report["failures_sample"][0]["kind"] == "lfs_pointer_not_materialized"


def test_verify_materialized_clone_rejects_wrong_sha(tmp_path):
    module = _module()
    expected = b"expected-bytes"
    relative = "clone_payload/releases/test/1--asset.bin"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupted-byte")
    _write_manifest(tmp_path, payload=expected, path=relative)

    report = module.verify(tmp_path)

    assert report["complete"] is False
    assert report["failure_count"] == 1
    assert report["failures_sample"][0]["kind"] in {"size", "sha256"}
