from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_clone_payload_completeness_test",
        ROOT / "tools" / "check_clone_payload_completeness.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_lfs_pointer_exact_identity():
    module = _module()
    sha = "a" * 64
    raw = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{sha}\n"
        "size 12345\n"
    ).encode()

    assert module.parse_lfs_pointer(raw) == (sha, 12345)


def test_audit_reports_exact_byte_parity(monkeypatch, tmp_path):
    module = _module()
    sha = "b" * 64
    source = {
        101: {
            "release_id": 1,
            "release_tag": "data-v2-test",
            "asset_name": "trades.bin",
            "bytes": 42,
            "source_digest": "sha256:" + sha,
        }
    }
    manifest = {
        "schema": "alina.clone_payload_manifest.v1",
        "entries": [
            {
                "asset_id": 101,
                "bytes": 42,
                "sha256": sha,
                "clone_path": "clone_payload/releases/data-v2-test/101--trades.bin",
            }
        ],
    }
    monkeypatch.setattr(module, "source_inventory", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(module.mirror, "load_manifest", lambda _path: manifest)
    monkeypatch.setattr(
        module,
        "git_pointer_for_path",
        lambda *_args, **_kwargs: (sha, 42),
    )

    report = module.audit(
        "owner/repo",
        root=tmp_path,
        token=None,
        verify_git_pointers=True,
    )

    assert report["complete"] is True
    assert report["source_assets"] == report["clone_assets"] == 1
    assert report["source_bytes"] == report["clone_bytes"] == 42
    assert report["missing_asset_count"] == 0
    assert report["mismatch_count"] == 0


def test_audit_fails_closed_on_one_missing_asset(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(
        module,
        "source_inventory",
        lambda *_args, **_kwargs: {
            1: {"bytes": 5, "source_digest": ""},
            2: {"bytes": 7, "source_digest": ""},
        },
    )
    monkeypatch.setattr(
        module.mirror,
        "load_manifest",
        lambda _path: {
            "schema": "alina.clone_payload_manifest.v1",
            "entries": [
                {
                    "asset_id": 1,
                    "bytes": 5,
                    "sha256": "c" * 64,
                    "clone_path": "clone_payload/releases/x/1--a.bin",
                }
            ],
        },
    )

    report = module.audit(
        "owner/repo",
        root=tmp_path,
        token=None,
        verify_git_pointers=False,
    )

    assert report["complete"] is False
    assert report["source_bytes"] == 12
    assert report["clone_bytes"] == 5
    assert report["missing_asset_count"] == 1
    assert report["missing_asset_ids_sample"] == [2]
