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
        "total_assets": 1,
        "total_bytes": 42,
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
        "git_pointers_for_paths",
        lambda _root, paths: {path: (sha, 42) for path in paths},
    )
    monkeypatch.setattr(
        module,
        "git_tracked_payload_paths",
        lambda _root: {"clone_payload/releases/data-v2-test/101--trades.bin"},
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
            "total_assets": 1,
            "total_bytes": 5,
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


def test_git_pointers_for_paths_reads_many_blobs_in_one_batch(tmp_path):
    module = _module()
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
    )
    paths = []
    expected = {}
    for index in range(3):
        sha = f"{index + 1:x}" * 64
        path = tmp_path / "clone_payload" / "releases" / f"{index}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{sha}\n"
            f"size {100 + index}\n",
            encoding="utf-8",
        )
        rel = path.relative_to(tmp_path).as_posix()
        paths.append(rel)
        expected[rel] = (sha, 100 + index)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "pointers"], check=True, capture_output=True)

    assert module.git_pointers_for_paths(tmp_path, paths) == expected



def test_audit_rejects_extra_tracked_lfs_asset(monkeypatch, tmp_path):
    module = _module()
    sha = "a" * 64
    path = "clone_payload/releases/t/1--asset.bin"
    monkeypatch.setattr(module, "source_inventory", lambda *_a, **_k: {
        1: {"bytes": 4, "source_digest": "sha256:" + sha},
    })
    monkeypatch.setattr(module.mirror, "load_manifest", lambda _p: {
        "schema": "alina.clone_payload_manifest.v1",
        "total_assets": 1,
        "total_bytes": 4,
        "entries": [{
            "asset_id": 1, "bytes": 4, "sha256": sha, "clone_path": path,
        }],
    })
    monkeypatch.setattr(module, "git_pointers_for_paths", lambda _r, _p: {
        path: (sha, 4),
    })
    monkeypatch.setattr(
        module,
        "git_tracked_payload_paths",
        lambda _r: {path, "clone_payload/releases/t/unlisted.bin"},
    )

    report = module.audit(
        "owner/repo", root=tmp_path, token=None, verify_git_pointers=True,
    )

    assert report["complete"] is False
    assert any(row["kind"] == "tracked_payload_set" for row in report["mismatches_sample"])


def test_audit_accepts_zero_length_release_asset(monkeypatch, tmp_path):
    module = _module()
    import hashlib
    sha = hashlib.sha256(b"").hexdigest()
    path = "clone_payload/releases/t/2--empty.bin"
    monkeypatch.setattr(module, "source_inventory", lambda *_a, **_k: {
        2: {"bytes": 0, "source_digest": "sha256:" + sha},
    })
    monkeypatch.setattr(module.mirror, "load_manifest", lambda _p: {
        "schema": "alina.clone_payload_manifest.v1",
        "total_assets": 1,
        "total_bytes": 0,
        "entries": [{"asset_id": 2, "bytes": 0, "sha256": sha, "clone_path": path}],
    })
    monkeypatch.setattr(module, "git_tracked_payload_paths", lambda _r: {path})
    monkeypatch.setattr(module, "git_pointers_for_paths", lambda _r, _p: {
        path: (sha, 0),
    })
    report = module.audit("owner/repo", root=tmp_path, token=None, verify_git_pointers=True)
    assert report["complete"] is True


def test_git_tracked_payload_inventory_excludes_untracked_files(tmp_path):
    module = _module()
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"], check=True)
    target = tmp_path / "clone_payload" / "releases" / "t" / "1--test.bin"
    target.parent.mkdir(parents=True)
    target.write_text("version https://git-lfs.github.com/spec/v1\n" + "oid sha256:" + ("a" * 64) + "\nsize 123\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "data"], check=True, capture_output=True)
    (target.parent / "untracked.bin").write_bytes(b"extra")

    assert module.git_tracked_payload_paths(tmp_path) == {
        "clone_payload/releases/t/1--test.bin"
    }


def test_empty_mirror_is_fast_fail_without_release_api_calls(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module.mirror, "load_manifest", lambda _p: {
        "schema": "alina.clone_payload_manifest.v1",
        "total_assets": 0,
        "total_bytes": 0,
        "entries": [],
    })
    monkeypatch.setattr(
        module, "source_inventory",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("empty mirror must not exhaust remote API quota")
        ),
    )
    monkeypatch.setattr(module, "git_tracked_payload_paths", lambda _r: set())
    report = module.audit("owner/repo", root=tmp_path, token=None, verify_git_pointers=True)
    assert report["complete"] is False
    assert report["reason"] == "MIRROR_NOT_STARTED"
    assert report["source_bytes"] is None
    assert report["clone_bytes"] == 0
    assert report["source_inventory_checked"] is False



def test_empty_manifest_detects_orphan_payload_without_remote_api(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module.mirror, "load_manifest", lambda _p: {
        "schema": "alina.clone_payload_manifest.v1",
        "entries": [], "total_assets": 0, "total_bytes": 0,
    })
    monkeypatch.setattr(
        module, "source_inventory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no remote call expected")
        ),
    )
    monkeypatch.setattr(
        module, "git_tracked_payload_paths",
        lambda _root: {"clone_payload/releases/unknown.bin"},
    )
    report = module.audit(
        "owner/repo", root=tmp_path, token=None, verify_git_pointers=True,
    )
    assert report["complete"] is False
    assert report["tracked_payload_without_manifest_count"] == 1
    assert report["mismatch_count"] == 1


def test_force_inventory_source_does_not_claim_complete_on_empty_mirror(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module.mirror, "load_manifest", lambda _p: {
        "schema": "alina.clone_payload_manifest.v1",
        "entries": [], "total_assets": 0, "total_bytes": 0,
    })
    monkeypatch.setattr(
        module, "source_inventory",
        lambda *_args, **_kwargs: {42: {"bytes": 23, "source_digest": ""}},
    )
    monkeypatch.setattr(module, "git_tracked_payload_paths", lambda _root: set())
    report = module.audit(
        "owner/repo", root=tmp_path, token=None, verify_git_pointers=True,
        force_source_inventory=True,
    )
    assert report["complete"] is False
    assert report["source_assets"] == 1
    assert report["source_bytes"] == 23
    assert report["missing_asset_count"] == 1


def test_manifest_totals_conflict_is_fail_closed(monkeypatch, tmp_path):
    module = _module()
    path = "clone_payload/releases/r/1--a.bin"
    sha = "a" * 64
    monkeypatch.setattr(module, "source_inventory", lambda *_a, **_k: {
        1: {"bytes": 12, "source_digest": "sha256:" + sha},
    })
    monkeypatch.setattr(module.mirror, "load_manifest", lambda _p: {
        "schema": "alina.clone_payload_manifest.v1",
        "entries": [{"asset_id": 1, "bytes": 12, "sha256": sha, "clone_path": path}],
        "total_assets": 0,
        "total_bytes": 12,
    })
    monkeypatch.setattr(module, "git_tracked_payload_paths", lambda _r: {path})
    monkeypatch.setattr(module, "git_pointers_for_paths", lambda _r, _p: {path: (sha, 12)})
    report = module.audit("owner/repo", root=tmp_path, token=None, verify_git_pointers=True)
    assert report["complete"] is False
    assert any(m["kind"] == "manifest_totals" for m in report["mismatches_sample"])
