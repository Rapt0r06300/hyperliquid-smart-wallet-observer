from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_symlink_setup_skips_only_windows_privilege_error(tmp_path, monkeypatch):
    error = OSError("symbolic-link privilege required")
    error.winerror = 1314

    def fail_symlink(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(Path, "symlink_to", fail_symlink)
    with pytest.raises(pytest.skip.Exception, match="symlink privilege"):
        _create_symlink_or_skip(tmp_path / "link", tmp_path / "target")


def test_symlink_setup_does_not_hide_other_permission_errors(tmp_path, monkeypatch):
    def fail_symlink(*_args, **_kwargs):
        raise PermissionError(13, "unrelated filesystem permission failure")

    monkeypatch.setattr(Path, "symlink_to", fail_symlink)
    with pytest.raises(PermissionError, match="unrelated filesystem permission failure"):
        _create_symlink_or_skip(tmp_path / "link", tmp_path / "target")


def _create_symlink_or_skip(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except NotImplementedError:
        pytest.skip("symlinks are not supported by this platform")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable (WinError 1314)")
        raise


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
                "bytes": len(shard),
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
    def fake_download(url, target, **_kwargs):
        payload = payloads[url]
        target.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", fake_download)

    report = module.restore_everything("owner/repo", tmp_path)

    assert report["release_count"] == 1
    assert report["asset_count"] == 2
    assert report["downloaded"] == 2
    assert report["source_asset_bytes"] == len(shard) + len(manifest_bytes)
    assert report["verified_asset_bytes"] == report["source_asset_bytes"]
    assert report["missing_asset_bytes"] == 0
    assert report["source_byte_parity"] is True
    assert report["assets_verified"] is True
    assert report["restore_complete"] is False
    assert report["published_volume_bytes"] == len(shard) + len(manifest_bytes)
    assert report["restored_volume_bytes"] == report["published_volume_bytes"]
    assert report["verified_volume_bytes"] == report["published_volume_bytes"]
    assert report["missing_volume_bytes"] == 0
    assert report["corrupt_volume_bytes"] == 0
    assert report["non_verifiable_volume_bytes"] == 0
    assert report["quarantine_volume_bytes"] == len(shard)
    assert report["snapshots_reconstructed"] == 0
    assert report["snapshot_files_reconstructed"] == 0
    assert report["failures"] == []
    assert report["verification_failures"] == 0
    assert report["run_manifest_checks"][0]["status"] == "OK"
    assert report["status"] == "ASSETS_VERIFIED_ONLY"  # no canonical SAFE catalog supplied
    assert len(report["source_inventory_sha256"]) == 64
    identities = report["releases"][0]["assets"]
    assert identities[0]["sha256"] == shard_sha
    assert identities[0]["size_bytes"] == len(shard)
    assert identities[0]["source_repository"] == "owner/repo"
    assert identities[0]["release_tag"] == "data-v2-test"
    assert identities[0]["expected_sha256"] == shard_sha
    assert identities[0]["calculated_sha256"] == shard_sha
    assert identities[0]["downloaded_size_bytes"] == len(shard)
    assert identities[0]["verification_status"] == "VERIFIED"
    assert Path(identities[0]["destination"]) == (tmp_path / "releases" / "data-v2-test" / "trades.jsonl.gz")
    assert (tmp_path / "releases" / "data-v2-test" / "trades.jsonl.gz").read_bytes() == shard


def test_download_asset_rejects_digest_mismatch(tmp_path, monkeypatch):
    module = _module()
    good = b"expected"
    bad = b"corrupted"
    asset = _asset("asset.bin", "https://example.invalid/asset", good)
    def fake_bad_download(_url, target, **_kwargs):
        target.write_bytes(bad)
        return len(bad), hashlib.sha256(bad).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", fake_bad_download)

    try:
        module.download_asset(asset, tmp_path)
    except module.RestoreError as exc:
        assert "size mismatch" in str(exc) or "sha256 mismatch" in str(exc)
        assert not (tmp_path / "asset.bin.partial").exists()
    else:
        raise AssertionError("corrupted restore asset must fail closed")


def test_corrupt_cached_partial_retries_once_from_byte_zero(tmp_path, monkeypatch):
    module = _module()
    payload = b"valid-release-bytes-after-retry"
    asset = _asset("asset.bin", "https://example.invalid/asset", payload)
    partial = tmp_path / "asset.bin.partial"
    partial.write_bytes(b"BAD!!")
    calls = []

    def simulate_range_then_clean_download(_url, path, **_kwargs):
        calls.append(path.read_bytes() if path.exists() else None)
        if len(calls) == 1:
            # Resumed HTTP 206 retained the corrupt prefix.
            bad = b"BAD!!" + payload[5:]
            path.write_bytes(bad)
            return len(bad), hashlib.sha256(bad).hexdigest()
        assert len(calls) == 2
        assert not path.exists(), "retry must start from byte zero"
        path.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", simulate_range_then_clean_download)
    receipt = module.download_asset(asset, tmp_path)

    assert calls == [b"BAD!!", None]
    assert receipt["status"] == "DOWNLOADED_VERIFIED"
    assert receipt["calculated_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / "asset.bin").read_bytes() == payload
    assert not partial.exists()


def test_short_resumed_partial_is_preserved_for_next_resume(tmp_path, monkeypatch):
    module = _module()
    payload = b"complete-valid-release-payload"
    asset = _asset("asset.bin", "https://example.invalid/asset", payload)
    partial = tmp_path / "asset.bin.partial"
    partial.write_bytes(b"STALE")
    calls = []

    def interrupted_resume(_url, path, **_kwargs):
        calls.append(path.read_bytes() if path.exists() else None)
        path.write_bytes(payload[:7])
        return 7, hashlib.sha256(payload[:7]).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", interrupted_resume)
    import pytest
    with pytest.raises(module.RestoreError, match="size mismatch"):
        module.download_asset(asset, tmp_path)
    assert calls == [b"STALE"]
    assert partial.read_bytes() == payload[:7]
    assert not (tmp_path / "asset.bin").exists()


def test_corrupt_cached_partial_stays_fail_closed_after_retry(tmp_path, monkeypatch):
    module = _module()
    payload = b"valid-release-bytes-after-retry"
    asset = _asset("asset.bin", "https://example.invalid/asset", payload)
    partial = tmp_path / "asset.bin.partial"
    partial.write_bytes(b"BAD!!")
    calls = []

    def always_corrupt(_url, path, **_kwargs):
        calls.append(path.read_bytes() if path.exists() else None)
        bad = b"BAD!!" + payload[5:]
        path.write_bytes(bad)
        return len(bad), hashlib.sha256(bad).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", always_corrupt)
    import pytest
    with pytest.raises(module.RestoreError, match="sha256 mismatch"):
        module.download_asset(asset, tmp_path)
    assert calls == [b"BAD!!", None]
    assert not partial.exists()
    assert not (tmp_path / "asset.bin").exists()


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


def test_streaming_download_writes_in_chunks_without_request_buffer(tmp_path, monkeypatch):
    module = _module()
    payload = b"a" * (9 * 1024 * 1024) + b"tail"

    class Response:
        def __init__(self, data):
            self.data = data
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            if self.offset >= len(self.data):
                return b""
            part = self.data[self.offset : self.offset + size]
            self.offset += len(part)
            return part

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(payload),
    )
    target = tmp_path / "asset.partial"

    size, digest = module._download_to_path(
        "https://example.invalid/large-asset",
        target,
    )

    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert target.read_bytes() == payload


def test_safe_component_is_collision_resistant_for_sanitized_names():
    module = _module()

    first = module._safe_component("tag/with/slash")
    second = module._safe_component("tag_with_slash")

    assert first != second
    assert "/" not in first


def test_preflight_estimates_bytes_without_downloading(tmp_path, monkeypatch):
    module = _module()
    payload = b"published bytes"
    releases = [{"tag_name": "data-v2-test",
                 "assets": [_asset("asset.bin", "https://example.invalid/asset", payload)]}]
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter(releases))
    monkeypatch.setattr(
        module, "_download_to_path",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("preflight must not download any Release asset")
        ),
    )
    class Usage:
        free = 0
    monkeypatch.setattr(module.shutil, "disk_usage", lambda *_a: Usage())
    root = tmp_path / "restored"
    report = module.restore_everything("owner/repo", root, preflight_only=True)
    assert report["status"] == "PREFLIGHT_INSUFFICIENT_DISK"
    assert report["release_count"] == 1
    assert report["asset_count"] == 1
    assert report["pending_download_bytes"] == len(payload)
    assert report["enough_disk_for_release_assets"] is False
    assert (root / "RESTORE_PREFLIGHT.json").is_file()
    assert not (root / "RESTORE_REPORT.json").exists()


def test_preflight_cli_does_not_claim_completed_restore(tmp_path, monkeypatch, capsys):
    module = _module()
    def fake_restore(*_args, **kwargs):
        assert kwargs["preflight_only"] is True
        return {"status": "PREFLIGHT_INSUFFICIENT_DISK",
                "enough_disk_for_release_assets": False}
    monkeypatch.setattr(module, "restore_everything", fake_restore)
    exit_code = module.main(["--everything", "--preflight-only",
                             "--destination", str(tmp_path / "restore")])
    assert exit_code == 3
    assert "PREFLIGHT_INSUFFICIENT_DISK" in capsys.readouterr().out


def test_restore_fails_before_download_when_disk_is_insufficient(tmp_path, monkeypatch):
    module = _module()
    payload = b"x" * 1024
    releases = [
        {
            "tag_name": "data-v2-test",
            "assets": [
                _asset("asset.bin", "https://example.invalid/asset", payload),
                _asset("RUN_MANIFEST.json", "https://example.invalid/manifest", b'{"manifests":[]}'),
            ],
        }
    ]
    monkeypatch.setattr(module, "iter_releases", lambda *_args, **_kwargs: iter(releases))

    class Usage:
        total = 2048
        used = 2047
        free = 1

    monkeypatch.setattr(module.shutil, "disk_usage", lambda _path: Usage())
    monkeypatch.setattr(
        module,
        "_download_to_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("download must not start without enough disk")
        ),
    )

    try:
        module.restore_everything("owner/repo", tmp_path)
    except module.RestoreError as exc:
        assert "insufficient disk space" in str(exc)
    else:
        raise AssertionError("restore must fail closed when disk capacity is insufficient")



def test_iter_releases_uses_documented_embedded_assets_without_per_release_calls(monkeypatch):
    module = _module()
    def a(index):
        return {
            **_asset(f"part-{index:03}.bin", f"https://example.invalid/{index}", bytes([index % 256])),
            "id": index + 1,
            "state": "uploaded",
        }
    releases = [{"id": 123, "tag_name": "data-v2-many", "assets": [a(i) for i in range(151)]}]
    calls = []
    def fake_json(url, **_kwargs):
        calls.append(url)
        if "/releases?" in url:
            return releases
        raise AssertionError(url)
    monkeypatch.setattr(module, "_json", fake_json)
    rows = list(module.iter_releases("owner/repo"))
    assert len(rows) == 1
    assert len(rows[0]["assets"]) == 151
    assert rows[0]["assets"][-1]["name"] == "part-150.bin"
    assert len(calls) == 1



def test_iter_releases_handles_overlapping_pages_from_live_publication(monkeypatch):
    module = _module()
    # Page 2 shifts right after a new Release appears while COLLECT continues.
    calls = []
    def fake_json(url, **_kwargs):
        calls.append(url)
        if "/assets?" in url:
            return []
        page = int(url.split("&page=")[1])
        ids = {
            1: list(range(200, 100, -1)),
            2: list(range(101, 1, -1)),  # id=101 repeats from page 1
            3: [1],
        }.get(page, [])
        return [{"id": i, "tag_name": f"data-v2-{i}", "assets": []}
                for i in ids]
    monkeypatch.setattr(module, "_json", fake_json)
    found = list(module.iter_releases("owner/repo"))
    assert [r["id"] for r in found] == list(range(200, 0, -1))
    assert len(calls) == 3


def test_iter_releases_rejects_conflicting_overlap(monkeypatch):
    import pytest
    module = _module()
    def fake_json(url, **_kwargs):
        if "/assets?" in url:
            return []
        page = int(url.split("&page=")[1])
        if page == 1:
            return [{"id": i, "tag_name": f"data-v2-{i}", "assets": []}
                    for i in range(1, 101)]
        if page == 2:
            return [{"id": 99, "tag_name": "changed-tag", "assets": []}]
        return []
    monkeypatch.setattr(module, "_json", fake_json)
    with pytest.raises(module.RestoreError, match="changed tag"):
        list(module.iter_releases("owner/repo"))


def test_iter_releases_504_retries_same_absolute_offset(monkeypatch):
    module = _module()
    calls = []

    def fake_json(url, **_kwargs):
        calls.append(url)
        if "/assets?" in url:
            i = int(url.split("/releases/")[1].split("/assets?")[0]) - 1
            return [{
                "id": i + 100, "name": "shard.jsonl.gz", "size": 1,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": f"https://example.invalid/{i}",
                "state": "uploaded",
            }]
        if "per_page=100&page=2" in url:
            raise module.RestoreError("HTTP 504 for deep Release page")
        size = int(url.split("per_page=")[1].split("&")[0])
        page = int(url.split("&page=")[1])
        offset = (page - 1) * size
        return [
            {"id": i + 1, "tag_name": f"data-v2-{i}",
             "assets": [{
                 "id": i + 100,
                 "name": "shard.jsonl.gz",
                 "size": 1,
                 "digest": "sha256:" + "a" * 64,
                 "browser_download_url": f"https://example.invalid/{i}",
                 "state": "uploaded",
             }]}
            for i in range(offset, min(112, offset + size))
        ]

    monkeypatch.setattr(module, "_json", fake_json)
    rows = list(module.iter_releases("owner/repo"))
    assert len(rows) == 112
    assert len({row["id"] for row in rows}) == 112
    assert any("per_page=50&page=3" in url for url in calls)


def test_iter_releases_uses_published_inventory_beyond_github_1000_cap(monkeypatch):
    module = _module()
    inventory_asset = {
        **_asset(
            "RESTORE_INVENTORY.json.gz",
            "https://example.invalid/restore-inventory",
            b"inventory",
        ),
        "id": 9001,
        "state": "uploaded",
    }

    def fake_json(url, **_kwargs):
        page = int(url.split("&page=")[1])
        if page == 11:
            raise module.RestoreError(
                'HTTP 422: {"message":"Only the first 1000 results are available."}'
            )
        start = (page - 1) * 100
        rows = [
            {"id": i + 1, "tag_name": f"release-{i + 1}", "assets": []}
            for i in range(start, start + 100)
        ]
        if page == 1:
            rows[0] = {
                "id": 9999,
                "tag_name": "alina-restore-inventory-42",
                "assets": [inventory_asset],
            }
        return rows

    historical = [
        {"id": 2, "tag_name": "release-2", "assets": []},
        {"id": 2001, "tag_name": "historical-2001", "assets": []},
    ]
    monkeypatch.setattr(module, "_json", fake_json)
    monkeypatch.setattr(
        module,
        "_read_restore_inventory_asset",
        lambda *_args, **_kwargs: historical,
        raising=False,
    )

    rows = list(module.iter_releases("owner/repo"))
    assert len(rows) == 1001
    assert rows[-1]["tag_name"] == "historical-2001"


def test_published_inventory_cache_is_sha_verified_and_reused(tmp_path, monkeypatch):
    module = _module()
    payload = {
        "schema": "alina.restore_inventory.v1",
        "repository": "owner/repo",
        "releases": [],
    }
    compressed = gzip.compress(
        json.dumps(payload).encode("utf-8"), mtime=0,
    )
    asset = {
        **_asset(
            "RESTORE_INVENTORY.json.gz",
            "https://example.invalid/inventory",
            compressed,
        ),
        "id": 99,
        "state": "uploaded",
    }
    calls = []

    def download(_url, target, **_kwargs):
        calls.append(target)
        target.write_bytes(compressed)
        return len(compressed), hashlib.sha256(compressed).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", download)
    cache = tmp_path / "RESTORE_INVENTORY.json.gz"
    assert module._read_restore_inventory_asset(
        asset, "owner/repo", cache_path=cache,
    ) == []
    assert module._read_restore_inventory_asset(
        asset, "owner/repo", cache_path=cache,
    ) == []
    assert len(calls) == 1



def test_iter_releases_rejects_malformed_or_duplicate_asset_pages(monkeypatch):
    module = _module()
    asset = {**_asset("one.bin", "https://example.invalid/one", b"a"), "id": 7, "state": "uploaded"}
    def fake_json(url, **_kwargs):
        if "/releases?" in url:
            return [{"id": 1, "tag_name": "one", "assets": [asset, asset]}]
        raise AssertionError(url)
    monkeypatch.setattr(module, "_json", fake_json)
    import pytest
    with pytest.raises(module.RestoreError, match="duplicated asset id"):
        list(module.iter_releases("owner/repo"))


def test_iter_releases_rejects_asset_without_provable_hash(monkeypatch):
    module = _module()
    def fake_json(url, **_kwargs):
        if "/releases?" in url:
            return [{"id": 1, "tag_name": "one", "assets": [
                {**_asset("one.bin", "https://example.invalid/one", b"a"),
                 "id": 7, "state": "uploaded", "digest": None},
            ]}]
        raise AssertionError(url)
    monkeypatch.setattr(module, "_json", fake_json)
    import pytest
    with pytest.raises(module.RestoreError, match="SHA-256"):
        list(module.iter_releases("owner/repo"))


def test_restore_rejects_incomplete_inventory_before_any_download(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "iter_releases", lambda *_args, **_kwargs: iter([
        {"tag_name": "test", "assets": [
            _asset("same.bin", "https://example.invalid/1", b"a"),
            _asset("same.bin", "https://example.invalid/2", b"b"),
        ]}
    ]))
    monkeypatch.setattr(module, "_download_to_path", lambda *_a, **_kw: (_ for _ in ()).throw(
        AssertionError("must not download")
    ))
    import pytest
    with pytest.raises(module.RestoreError, match="duplicate"):
        module.restore_everything("owner/repo", tmp_path)


def test_download_asset_rejects_missing_hash_even_when_cached(tmp_path):
    module = _module()
    path = tmp_path / "asset.bin"
    path.write_bytes(b"saved")
    asset = _asset("asset.bin", "https://example.invalid/asset", b"saved")
    asset["digest"] = "sha256:not-a-hex-digest"
    import pytest
    with pytest.raises(module.RestoreError, match="SHA-256"):
        module.download_asset(asset, tmp_path)


def test_restore_materializes_only_proven_safe_replay_assets(tmp_path, monkeypatch):
    module = _module()
    safe = b'{"trade_id":"safe"}\n'
    partial = b'{"trade_id":"partial"}\n'
    manifest = {
        "schema": "alina.dataset_run_manifest.v2",
        "release_tag": "data-v2-classified",
        "manifests": [
            {
                "dataset_id": "safe-trades",
                "family": "trades",
                "quality_status": "SAFE",
                "validation_allowed": True,
                "replay_compatible": True,
                "asset_verified": True,
                "bytes": len(safe),
                "sha256": hashlib.sha256(safe).hexdigest(),
                "release": {
                    "repository": "owner/repo",
                    "release_tag": "data-v2-classified",
                    "asset_name": "safe.jsonl.gz",
                },
            },
            {
                "dataset_id": "partial-trades",
                "family": "trades",
                "quality_status": "PARTIAL",
                "validation_allowed": False,
                "replay_compatible": False,
                "asset_verified": True,
                "bytes": len(partial),
                "sha256": hashlib.sha256(partial).hexdigest(),
                "release": {
                    "repository": "owner/repo",
                    "release_tag": "data-v2-classified",
                    "asset_name": "partial.jsonl.gz",
                },
            },
        ],
    }
    manifest_bytes = json.dumps(manifest).encode()
    payloads = {
        "https://example.invalid/safe": safe,
        "https://example.invalid/partial": partial,
        "https://example.invalid/manifest": manifest_bytes,
    }
    release = {
        "tag_name": "data-v2-classified",
        "assets": [
            _asset("safe.jsonl.gz", "https://example.invalid/safe", safe),
            _asset("partial.jsonl.gz", "https://example.invalid/partial", partial),
            _asset("RUN_MANIFEST.json", "https://example.invalid/manifest", manifest_bytes),
        ],
    }
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([release]))
    monkeypatch.setattr(
        module,
        "_download_to_path",
        lambda url, target, **_k: (
            target.write_bytes(payloads[url]),
            hashlib.sha256(payloads[url]).hexdigest(),
        ),
    )

    report = module.restore_everything("owner/repo", tmp_path)

    usable = tmp_path / "usable" / "shards" / "data-v2-classified"
    quarantine = tmp_path / "quarantine" / "shards" / "data-v2-classified"
    assert (usable / "safe-trades.jsonl.gz").read_bytes() == safe
    assert not (usable / "partial-trades.jsonl.gz").exists()
    assert (quarantine / "partial-trades.jsonl.gz").read_bytes() == partial
    assert report["classification"]["usable_shards"] == 1
    assert report["classification"]["quarantined_shards"] == 1
    assert report["classification"]["usable_bytes"] == len(safe)
    assert report["classification"]["quarantined_bytes"] == len(partial)

    repeat = module.restore_everything("owner/repo", tmp_path)
    assert repeat["all_source_assets_accounted_for"]
    assert repeat["classification"]["skipped_verified_shards"] == 2
    assert repeat["classification"]["usable_shards"] == 1
    assert repeat["classification"]["quarantined_shards"] == 1

    # Certification requires catalog parity, not merely downloaded assets.
    safe_sha = hashlib.sha256(safe).hexdigest()
    catalog = tmp_path / "DATA_INDEX.json"
    metrics = tmp_path / "DATA_METRICS.json"
    catalog.write_text("{}", encoding="utf-8")
    metrics.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        module, "_load_current_safe_catalog",
        lambda *_a: (
            {"safe-trades": (safe_sha, "data-v2-classified")},
            {"source_index_sha256": "verified-test-catalog"},
        ),
    )
    certified = module.restore_everything(
        "owner/repo", tmp_path, catalog_path=catalog, metrics_path=metrics,
    )
    assert certified["status"] == "RESTORE_COMPLETE"
    assert certified["classification"]["missing_catalog_safe_shards"] == 0
    monkeypatch.setattr(
        module, "_load_current_safe_catalog",
        lambda *_a: (
            {
                "safe-trades": (safe_sha, "data-v2-classified"),
                "unpublished": ("a" * 64, "no-release"),
            },
            {"source_index_sha256": "verified-test-catalog"},
        ),
    )
    incomplete = module.restore_everything(
        "owner/repo", tmp_path, catalog_path=catalog, metrics_path=metrics,
    )
    assert incomplete["status"] == "RESTORE_INCOMPLETE"
    assert incomplete["classification"]["missing_catalog_safe_shards"] == 1
    assert any(
        row["error"] == "CATALOG_SAFE_SHARDS_NOT_RESTORED"
        for row in incomplete["classification"]["failures"]
    )


def test_restore_verifies_zip_member_before_usable_materialization(tmp_path, monkeypatch):
    module = _module()
    member = b'{"trade_id":"inside"}\n'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("inside.jsonl.gz", member)
    packed = buffer.getvalue()
    manifest = {
        "schema": "alina.dataset_run_manifest.v2",
        "release_tag": "data-v2-packed",
        "manifests": [{
            "dataset_id": "inside",
            "quality_status": "SAFE",
            "validation_allowed": True,
            "replay_compatible": True,
            "asset_verified": True,
            "bytes": len(member),
            "sha256": hashlib.sha256(member).hexdigest(),
            "release": {
                "repository": "owner/repo",
                "release_tag": "data-v2-packed",
                "asset_name": "packed.zip",
                "member_name": "inside.jsonl.gz",
                "storage": "zip_entry",
                "remote_size": len(packed),
                "remote_digest": "sha256:" + hashlib.sha256(packed).hexdigest(),
            },
        }],
    }
    manifest_bytes = json.dumps(manifest).encode()
    payloads = {
        "https://example.invalid/packed": packed,
        "https://example.invalid/manifest": manifest_bytes,
    }
    release = {
        "tag_name": "data-v2-packed",
        "assets": [
            _asset("packed.zip", "https://example.invalid/packed", packed),
            _asset("RUN_MANIFEST.json", "https://example.invalid/manifest", manifest_bytes),
        ],
    }
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([release]))
    monkeypatch.setattr(
        module,
        "_download_to_path",
        lambda url, target, **_k: (
            target.write_bytes(payloads[url]),
            hashlib.sha256(payloads[url]).hexdigest(),
        ),
    )

    report = module.restore_everything("owner/repo", tmp_path)

    restored = tmp_path / "usable" / "shards" / "data-v2-packed" / "inside.jsonl.gz"
    assert restored.read_bytes() == member
    assert report["classification"]["verified_zip_members"] == 1
    assert report["verification_failures"] == 0


def test_streaming_download_resumes_existing_partial_with_http_range(tmp_path, monkeypatch):
    module = _module()
    target = tmp_path / "asset.partial"
    target.write_bytes(b"prefix-")
    requests = []

    class Response:
        status = 206
        headers = {"Content-Range": "bytes 7-12/13"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if hasattr(self, "done"):
                return b""
            self.done = True
            return b"suffix"

    def open_response(request, **_kwargs):
        requests.append(request)
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", open_response)

    size, digest = module._download_to_path("https://example.invalid/asset", target)

    assert requests[0].headers["Range"] == "bytes=7-"
    assert target.read_bytes() == b"prefix-suffix"
    assert size == len(b"prefix-suffix")
    assert digest == hashlib.sha256(b"prefix-suffix").hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="regression specifique a MAX_PATH Windows")
def test_streaming_download_supports_windows_path_over_260_chars(tmp_path, monkeypatch):
    module = _module()
    parent = tmp_path / ("release-" + "r" * 110)
    parent.mkdir()
    name = "shard-" + "s" * 120 + ".jsonl.gz"
    target = parent / name
    assert len(str(target.with_suffix(target.suffix + ".partial"))) > 260

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if hasattr(self, "done"):
                return b""
            self.done = True
            return b"safe"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_a, **_k: Response())
    monkeypatch.setattr(module.time, "sleep", lambda *_a: None)

    result = module.download_asset(
        _asset(name, "https://example.invalid/asset", b"safe"), parent,
    )

    assert result["status"] == "DOWNLOADED_VERIFIED"
    assert result["calculated_sha256"] == hashlib.sha256(b"safe").hexdigest()
    assert Path("\\\\?\\" + str(target)).read_bytes() == b"safe"


def test_http_range_rejects_wrong_total_before_appending(tmp_path, monkeypatch):
    module = _module()
    target = tmp_path / "asset.partial"
    target.write_bytes(b"prefix-")

    class Response:
        status = 206
        headers = {"Content-Range": "bytes 7-12/14"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            raise AssertionError("invalid range must not stream")

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_a, **_k: Response())
    import pytest
    with pytest.raises(module.RestoreError, match="Content-Range"):
        module._download_to_path(
            "https://example.invalid/asset", target, max_bytes=13,
        )
    assert target.read_bytes() == b"prefix-"


def test_short_download_is_retained_as_resumable_partial(tmp_path, monkeypatch):
    module = _module()
    payload = b"complete-payload"
    prefix = payload[:8]
    asset = _asset("asset.bin", "https://example.invalid/asset", payload)

    def short_download(_url, target, **_kwargs):
        target.write_bytes(prefix)
        return len(prefix), hashlib.sha256(prefix).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", short_download)

    import pytest
    with pytest.raises(module.RestoreError, match="size mismatch"):
        module.download_asset(asset, tmp_path)

    assert (tmp_path / "asset.bin.partial").read_bytes() == prefix


def test_manifest_verification_rejects_direct_asset_without_size(tmp_path):
    module = _module()
    release = tmp_path / "data-v2-test"
    release.mkdir()
    shard = b"payload"
    (release / "asset.bin").write_bytes(shard)
    (release / "RUN_MANIFEST.json").write_text(
        json.dumps({
            "release_tag": "data-v2-test",
            "manifests": [{
                "release_asset": "asset.bin",
                "sha256": hashlib.sha256(shard).hexdigest(),
            }],
        }),
        encoding="utf-8",
    )

    checks = module._verify_run_manifests(tmp_path)

    assert checks[0]["status"] == "FAIL"
    assert checks[0]["bad_assets"] == 1


def test_cached_zip_with_valid_release_hash_but_invalid_structure_is_rejected(tmp_path):
    module = _module()
    payload = b"not-a-zip"
    asset = _asset("archive.zip", "https://example.invalid/archive", payload)
    (tmp_path / "archive.zip").write_bytes(payload)

    import pytest
    with pytest.raises(module.RestoreError, match="invalid ZIP archive"):
        module.download_asset(asset, tmp_path)


def test_safe_candidate_without_explicit_release_tag_stays_quarantined(tmp_path, monkeypatch):
    module = _module()
    shard = b'{"trade_id":"no-tag"}\n'
    manifest = {
        "schema": "alina.dataset_run_manifest.v2",
        "release_tag": "data-v2-no-implicit-tag",
        "manifests": [{
            "dataset_id": "no-implicit-tag",
            "quality_status": "SAFE",
            "validation_allowed": True,
            "replay_compatible": True,
            "asset_verified": True,
            "bytes": len(shard),
            "sha256": hashlib.sha256(shard).hexdigest(),
            "release": {
                "repository": "owner/repo",
                "asset_name": "shard.jsonl.gz",
            },
        }],
    }
    manifest_bytes = json.dumps(manifest).encode()
    payloads = {
        "https://example.invalid/shard": shard,
        "https://example.invalid/manifest": manifest_bytes,
    }
    release = {
        "tag_name": "data-v2-no-implicit-tag",
        "assets": [
            _asset("shard.jsonl.gz", "https://example.invalid/shard", shard),
            _asset("RUN_MANIFEST.json", "https://example.invalid/manifest", manifest_bytes),
        ],
    }
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([release]))
    monkeypatch.setattr(
        module,
        "_download_to_path",
        lambda url, target, **_k: (
            target.write_bytes(payloads[url]),
            hashlib.sha256(payloads[url]).hexdigest(),
        ),
    )

    report = module.restore_everything("owner/repo", tmp_path)

    assert report["classification"]["usable_shards"] == 0
    assert report["classification"]["quarantined_shards"] == 1


def test_restore_fails_closed_on_duplicate_dataset_identity(tmp_path):
    module = _module()
    root = tmp_path / "releases"
    release = root / "data-v2-duplicate"
    release.mkdir(parents=True)
    shard = b'{"trade_id":"distinct"}\n'
    (release / "shard.jsonl.gz").write_bytes(shard)
    row = {
        "dataset_id": "same-id",
        "quality_status": "SAFE",
        "validation_allowed": True,
        "replay_compatible": True,
        "asset_verified": True,
        "bytes": len(shard),
        "sha256": hashlib.sha256(shard).hexdigest(),
        "release": {
            "repository": "owner/repo",
            "release_tag": release.name,
            "asset_name": "shard.jsonl.gz",
        },
    }
    (release / "RUN_MANIFEST.json").write_text(
        json.dumps({"manifests": [row, dict(row)]}), encoding="utf-8"
    )

    result = module._materialize_classified_shards("owner/repo", root, tmp_path)
    assert result["usable_shards"] == 0
    assert result["excluded_rows"] == 2
    assert len(result["failures"]) == 2
    assert all(r["error"] == "DUPLICATE_DATASET_ID_IN_MANIFEST"
               for r in result["failures"])
    assert not (tmp_path / "usable" / "shards" / release.name / "same-id.jsonl.gz").exists()


def test_restore_revoked_safe_shard_is_quarantined_on_next_run(tmp_path):
    module = _module()
    root = tmp_path / "releases"
    release = root / "data-v2-revocation"
    release.mkdir(parents=True)
    shard = b'{"trade_id":"previously-safe"}\n'
    (release / "shard.jsonl.gz").write_bytes(shard)
    row = {
        "dataset_id": "once-safe",
        "quality_status": "SAFE",
        "validation_allowed": True,
        "replay_compatible": True,
        "asset_verified": True,
        "bytes": len(shard),
        "sha256": hashlib.sha256(shard).hexdigest(),
        "release": {
            "repository": "owner/repo",
            "release_tag": release.name,
            "asset_name": "shard.jsonl.gz",
        },
    }
    manifest_path = release / "RUN_MANIFEST.json"
    manifest_path.write_text(json.dumps({"manifests": [row]}), encoding="utf-8")
    first = module._materialize_classified_shards("owner/repo", root, tmp_path)
    usable = tmp_path / "usable" / "shards" / release.name / "once-safe.jsonl.gz"
    assert first["usable_shards"] == 1
    assert usable.read_bytes() == shard

    row["quality_status"] = "REJECT"
    row["validation_allowed"] = False
    manifest_path.write_text(json.dumps({"manifests": [row]}), encoding="utf-8")
    second = module._materialize_classified_shards("owner/repo", root, tmp_path)

    assert second["usable_shards"] == 0
    assert second["quarantined_shards"] == 1
    assert second["stale_usable_quarantined"] == 1
    assert second["stale_usable_quarantined_bytes"] == len(shard)
    assert second["failures"] == []
    assert not usable.exists()
    assert (release / "shard.jsonl.gz").read_bytes() == shard
    assert (tmp_path / "quarantine" / "shards" /
            release.name / "once-safe.jsonl.gz").read_bytes() == shard
    assert list((tmp_path / "quarantine" / "stale_usable" /
                 release.name).glob("once-safe.jsonl.gz.*.stale"))


def test_restore_rejects_zip_with_duplicate_member_names(tmp_path):
    module = _module()
    archive_path = tmp_path / "ambiguous.zip"
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("same.jsonl.gz", b"first")
            archive.writestr("same.jsonl.gz", b"second")
    import pytest
    with pytest.raises(module.RestoreError, match="duplicate ZIP members"):
        module._verify_zip_archive(archive_path, archive_path.name)


def test_restore_archives_orphan_release_without_claiming_safe(tmp_path, monkeypatch):
    module = _module()
    shard = b"unclassified-data"
    release = {
        "tag_name": "data-v2-missing-manifest",
        "assets": [_asset("trades.jsonl.gz", "https://example.invalid/shard", shard)],
    }
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([release]))
    def fake_download(_url, target, **_kw):
        target.write_bytes(shard)
        return len(shard), hashlib.sha256(shard).hexdigest()
    monkeypatch.setattr(module, "_download_to_path", fake_download)
    report = module.restore_everything("owner/repo", tmp_path)
    assert report["downloaded"] == 1
    assert report["unclaimed_dataset_release_count"] == 1
    assert report["classification"]["usable_shards"] == 0
    assert (tmp_path / "releases" / release["tag_name"] /
            "trades.jsonl.gz").read_bytes() == shard


def test_current_catalog_downgrade_overrides_historical_safe_manifest(tmp_path):
    module = _module()
    source = tmp_path / "releases" / "data-v2-historical-safe"
    source.mkdir(parents=True)
    shard = b'{"trade_id":"historical"}\n'
    (source / "trade.jsonl.gz").write_bytes(shard)
    manifest_row = {
        "dataset_id": "historical-safe",
        "quality_status": "SAFE",
        "validation_allowed": True,
        "replay_compatible": True,
        "asset_verified": True,
        "sha256": hashlib.sha256(shard).hexdigest(),
        "bytes": len(shard),
        "release": {
            "repository": "owner/repo",
            "release_tag": source.name,
            "asset_name": "trade.jsonl.gz",
        },
    }
    (source / "RUN_MANIFEST.json").write_text(
        json.dumps({"manifests": [manifest_row]}), encoding="utf-8"
    )
    result = module._materialize_classified_shards(
        "owner/repo", tmp_path / "releases", tmp_path,
        catalog_safe={},
    )
    assert result["usable_shards"] == 0
    assert result["quarantined_shards"] == 1
    assert not list((tmp_path / "usable").rglob("*.jsonl.gz"))
    assert list((tmp_path / "quarantine" / "shards").rglob("*.jsonl.gz"))


def test_canonical_catalog_requires_sha_bound_metrics_and_unique_id(tmp_path):
    module = _module()
    index_path = tmp_path / "DATA_INDEX.json"
    metrics_path = tmp_path / "DATA_METRICS.json"
    shard = {
        "dataset_id": "asset-1",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "validation_allowed": True,
        "asset_verified": True,
        "sha256": "a" * 64,
        "release_tag": "data-v2-e8",
    }
    index = {"shards": [shard]}
    index_path.write_text(json.dumps(index), encoding="utf-8")
    digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
    metrics = {
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": digest,
        "totals": {"TOTAL_SHARDS": 1},
    }
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    eligible, proof = module._load_current_safe_catalog(index_path, metrics_path)
    assert eligible == {"asset-1": ("a" * 64, "data-v2-e8")}
    assert proof["indexed_shards"] == 1
    assert proof["safe_catalog_shards"] == 1

    shard["quality_status"] = "REJECT"
    index_path.write_text(json.dumps({"shards": [shard]}), encoding="utf-8")
    import pytest
    with pytest.raises(module.RestoreError, match="does not match"):
        module._load_current_safe_catalog(index_path, metrics_path)

    new_digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
    metrics["source_index_sha256"] = new_digest
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    safe, _ = module._load_current_safe_catalog(index_path, metrics_path)
    assert safe == {}

    index_path.write_text(json.dumps({"shards": [shard, shard]}), encoding="utf-8")
    metrics["source_index_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
    metrics["totals"]["TOTAL_SHARDS"] = 2
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    with pytest.raises(module.RestoreError, match="duplicated dataset_id"):
        module._load_current_safe_catalog(index_path, metrics_path)


def test_safe_catalog_refuses_index_change_during_streamed_validation(
    tmp_path, monkeypatch,
):
    module = _module()
    index_path = tmp_path / "DATA_INDEX.json"
    metrics_path = tmp_path / "DATA_METRICS.json"
    safe_row = {
        "dataset_id": "safe-race",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "asset_verified": True,
        "validation_allowed": True,
        "sha256": "c" * 64,
        "release_tag": "data-v2-race",
    }
    original_index = {"shards": [safe_row]}
    index_path.write_text(json.dumps(original_index), encoding="utf-8")
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 1},
    }), encoding="utf-8")

    original_select = module.select_index_rows
    def mutate_after_selection(path, predicate, **kwargs):
        metadata, rows = original_select(path, predicate, **kwargs)
        index_path.write_text(json.dumps({"shards": []}), encoding="utf-8")
        return metadata, rows
    monkeypatch.setattr(module, "select_index_rows", mutate_after_selection)

    with pytest.raises(module.RestoreError, match="changed during validation"):
        module._load_current_safe_catalog(index_path, metrics_path)



def test_replay_ready_plan_selects_verified_rows_without_reconstructing_catalog(
    tmp_path, monkeypatch, capsys,
):
    module = _module()
    from tools.partitioned_data_index import partition_index

    raw = b"safe-data"
    row = {
        "dataset_id": "safe-once",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "release_tag": "data-v2-test",
        "release_asset": "safe.jsonl.gz",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    index_path = tmp_path / "DATA_INDEX.json"
    root, partitions = partition_index(
        {"schema": "alina.dataset_index.v1", "shards": [row]},
        max_partition_bytes=4096,
    )
    index_path.write_text(json.dumps(root), encoding="utf-8")
    for relative, payload in partitions.items():
        target = index_path.parent / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    metrics_path = tmp_path / "DATA_METRICS.json"
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 1},
    }), encoding="utf-8")

    def forbidden_full_read(*_args, **_kwargs):
        raise AssertionError("replay-ready must not reconstruct the full catalogue")
    monkeypatch.setattr(module, "read_index", forbidden_full_read, raising=False)

    proof, rows, required = module._load_replay_ready_plan(index_path, metrics_path)
    assert proof["safe_catalog_shards"] == 1
    assert [item["dataset_id"] for item in rows] == ["safe-once"]
    assert len(required) == 1
    assert "ALINA_RESTORE_PHASE=SAFE_PLAN_READY" in capsys.readouterr().err


def test_copy_vault_restore_plan_is_scoped_to_all_copy_vault_safe_families(tmp_path):
    module = _module()
    index_path = tmp_path / "DATA_INDEX.json"
    metrics_path = tmp_path / "DATA_METRICS.json"
    rows = [
        {
            "dataset_id": "cv-fill", "family": "copy_vault_fills",
            "quality_status": "SAFE", "replay_compatible": True,
            "release_tag": "cv-release", "release_asset": "fills.jsonl.gz",
            "bytes": 11, "sha256": "a" * 64,
        },
        {
            "dataset_id": "cv-position", "family": "copy_vault_positions",
            "quality_status": "SAFE", "replay_compatible": True,
            "release_tag": "cv-release", "release_asset": "positions.jsonl.gz",
            "bytes": 13, "sha256": "b" * 64,
        },
        {
            "dataset_id": "other-safe", "family": "trades",
            "quality_status": "SAFE", "replay_compatible": True,
            "release_tag": "other-release", "release_asset": "trades.jsonl.gz",
            "bytes": 17, "sha256": "c" * 64,
        },
        {
            "dataset_id": "cv-partial", "family": "copy_vault_l2",
            "quality_status": "PARTIAL", "replay_compatible": False,
            "release_tag": "cv-release", "release_asset": "partial.jsonl.gz",
            "bytes": 19, "sha256": "d" * 64,
        },
    ]
    index_path.write_text(json.dumps({"schema": "alina.data_index.v2", "shards": rows}),
                          encoding="utf-8")
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": len(rows)},
    }), encoding="utf-8")

    proof, selected, required = module._load_replay_ready_plan(
        index_path, metrics_path, copy_vault_only=True,
    )

    assert proof["indexed_shards"] == 4
    assert proof["safe_catalog_shards"] == 2
    assert proof["selection_scope"] == "COPY_VAULT_ONLY"
    assert proof["selection_families"] == [
        "copy_vault_fills", "copy_vault_positions",
    ]
    assert [row["dataset_id"] for row in selected] == ["cv-fill", "cv-position"]
    assert len(required) == 2


def test_catalog_refuses_explicitly_denied_safe_and_accepts_compact_evidence(tmp_path):
    import pytest
    module = _module()
    index_path = tmp_path / "DATA_INDEX.json"
    metrics_path = tmp_path / "DATA_METRICS.json"
    row = {
        "dataset_id": "uncertified-safe",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "asset_verified": True,
        "validation_allowed": True,
        "sha256": "b" * 64,
        "bytes": 23,
        "release_tag": "data-v2-test",
        "release_asset": "uncertified-safe.jsonl.gz",
    }

    def write(candidate):
        index_path.write_text(json.dumps({"shards": [candidate]}), encoding="utf-8")
        metrics_path.write_text(json.dumps({
            "schema_version": "alina.data_metrics.v4",
            "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "totals": {"TOTAL_SHARDS": 1},
        }), encoding="utf-8")

    # The compact index can omit redundant flags; restored bytes are still
    # verified against the immutable GitHub Release and logical shard SHA.
    compact = {key: value for key, value in row.items()
               if key not in {"asset_verified", "validation_allowed"}}
    write(compact)
    _proof, rows, _required = module._load_replay_ready_plan(index_path, metrics_path)
    assert [item["dataset_id"] for item in rows] == ["uncertified-safe"]

    for invalid in ("asset_verified", "validation_allowed", "replay_compatible",
                    "sha256", "release_tag"):
        candidate = dict(row)
        if invalid in {"asset_verified", "validation_allowed"}:
            candidate[invalid] = False
        else:
            candidate.pop(invalid)
        write(candidate)
        with pytest.raises(module.RestoreError, match="SAFE_CATALOG_NOT_FULLY_CERTIFIED"):
            module._load_replay_ready_plan(index_path, metrics_path)



def test_restore_rejects_stale_catalog_before_release_transfer(tmp_path, monkeypatch):
    module = _module()
    index_path = tmp_path / "index.json"
    metrics_path = tmp_path / "metrics.json"
    index_path.write_text(json.dumps({"shards": []}), encoding="utf-8")
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": "0" * 64,
        "totals": {"TOTAL_SHARDS": 0},
    }), encoding="utf-8")
    monkeypatch.setattr(
        module, "iter_releases",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("stale catalog must abort before listing Releases")
        ),
    )
    import pytest
    with pytest.raises(module.RestoreError, match="does not match"):
        module.restore_everything(
            "owner/repo", tmp_path / "restore",
            catalog_path=index_path, metrics_path=metrics_path,
        )


def test_restore_ignores_cached_release_absent_from_current_inventory(tmp_path, monkeypatch):
    module = _module()
    old_release = tmp_path / "releases" / "data-v2-removed"
    old_release.mkdir(parents=True)
    stale_shard = b'{"trade_id":"previously-safe"}\n'
    (old_release / "old.jsonl.gz").write_bytes(stale_shard)
    (old_release / "RUN_MANIFEST.json").write_text(
        json.dumps({
            "manifests": [{
                "dataset_id": "removed-trades",
                "quality_status": "SAFE",
                "validation_allowed": True,
                "replay_compatible": True,
                "asset_verified": True,
                "bytes": len(stale_shard),
                "sha256": hashlib.sha256(stale_shard).hexdigest(),
                "release": {
                    "repository": "owner/repo",
                    "release_tag": old_release.name,
                    "asset_name": "old.jsonl.gz",
                },
            }],
        }),
        encoding="utf-8",
    )
    previously_usable = (
        tmp_path / "usable" / "shards" / old_release.name / "removed-trades.jsonl.gz"
    )
    previously_usable.parent.mkdir(parents=True)
    previously_usable.write_bytes(stale_shard)

    current_manifest = b'{"manifests":[]}'
    monkeypatch.setattr(module, "iter_releases", lambda *_args, **_kwargs: iter([{
        "tag_name": "data-v2-current",
        "assets": [_asset(
            "RUN_MANIFEST.json", "https://example.invalid/current",
            current_manifest,
        )],
    }]))

    def fake_download(_url, target, **_kwargs):
        target.write_bytes(current_manifest)
        return len(current_manifest), hashlib.sha256(current_manifest).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", fake_download)
    report = module.restore_everything("owner/repo", tmp_path)

    assert report["release_count"] == 1
    assert report["verification_failures"] == 0
    assert len(report["run_manifest_checks"]) == 1
    assert report["classification"]["usable_shards"] == 0
    assert report["classification"]["ignored_stale_release_manifests"] == 1
    assert report["classification"]["stale_usable_quarantined"] == 1
    assert not previously_usable.exists()
    assert list((tmp_path / "quarantine" / "stale_usable").rglob("*.stale"))
    assert (old_release / "old.jsonl.gz").read_bytes() == stale_shard



def test_restore_rejects_zip_unsafe_members_and_symlinks(tmp_path):
    import stat

    module = _module()
    for member in (
        "../../outside.jsonl.gz",
        "/absolute/file.jsonl.gz",
        "C:/drive/file.jsonl.gz",
        "dir\\\\windows.jsonl.gz",
        "folder/../escape.jsonl.gz",
        "CON.txt",
        "folder/trailing. ",
    ):
        archive_path = tmp_path / "unsafe.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(member, b"not safe")
        with pytest.raises(module.RestoreError, match="unsafe ZIP member"):
            module._verify_zip_archive(archive_path, archive_path.name)

    archive_path = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("link.jsonl.gz")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(link, "../../escape")
    with pytest.raises(module.RestoreError, match="unsafe ZIP member type"):
        module._verify_zip_archive(archive_path, archive_path.name)


def test_materialize_safe_shard_uses_windows_io_path_for_long_target(
    tmp_path, monkeypatch,
):
    module = _module()
    payload = b'{"trade_id":"long-windows-path"}\n'
    tag = "data-v2-long-target"
    dataset_id = "safe-" + ("x" * 210)
    releases_root = tmp_path / "releases"
    source = releases_root / tag / "source.jsonl.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    destination = tmp_path / "restore"
    redirected_root = tmp_path / "extended-path-io"
    original_windows_io_path = module._windows_io_path

    def redirect_materialized_target(path):
        path = Path(path)
        usable_root = destination / "usable" / "shards"
        try:
            relative = path.relative_to(usable_root)
        except ValueError:
            return original_windows_io_path(path)
        if len(relative.parts) == 1:
            return redirected_root
        suffix = ".partial" if path.name.endswith(".partial") else ""
        return redirected_root / f"target.jsonl.gz{suffix}"

    monkeypatch.setattr(module, "_windows_io_path", redirect_materialized_target)
    row = {
        "dataset_id": dataset_id,
        "release_tag": tag,
        "release_asset": source.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    result = module._materialize_catalog_safe_shards(
        [row], releases_root, destination, prune_stale=False,
    )

    target = redirected_root / "target.jsonl.gz"
    assert result["failures"] == []
    assert result["materialization_complete"] is True
    assert result["usable_shards"] == 1
    assert target.read_bytes() == payload
    assert not (destination / "usable" / "shards" / tag / target.name).exists()


def test_materialize_safe_shards_verifies_existing_targets_concurrently(
    tmp_path, monkeypatch,
):
    import threading
    import time

    module = _module()
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def slow_verified(_path, _row):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return True

    monkeypatch.setattr(module, "_verified_row_bytes", slow_verified)
    rows = [
        {
            "dataset_id": f"safe-{index}",
            "release_tag": "data-v2-parallel",
            "release_asset": "source.jsonl.gz",
            "bytes": 1,
            "sha256": hashlib.sha256(b"x").hexdigest(),
        }
        for index in range(12)
    ]
    destination = tmp_path / "restore"
    target_root = destination / "usable" / "shards" / "data-v2-parallel"
    target_root.mkdir(parents=True)
    for row in rows:
        (target_root / f"{row['dataset_id']}.jsonl.gz").write_bytes(b"x")

    result = module._materialize_catalog_safe_shards(
        rows, tmp_path / "releases", destination,
        prune_stale=False,
    )

    assert result["materialization_complete"] is True
    assert result["skipped_verified_shards"] == len(rows)
    assert maximum_active >= 2


def test_materialize_safe_shards_persists_alinasync_validation_and_reuses_it(
    tmp_path, monkeypatch,
):
    import sqlite3

    module = _module()
    payload = gzip.compress(b'{"trade_id":"safe"}\n', mtime=0)
    digest = hashlib.sha256(payload).hexdigest()
    tag = "data-v2-durable-safe-state"
    row = {
        "dataset_id": "safe-durable-one",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "validation_allowed": True,
        "asset_verified": True,
        "release_tag": tag,
        "release_asset": "safe.jsonl.gz",
        "bytes": len(payload),
        "sha256": digest,
    }
    destination = tmp_path / "restore"
    source = tmp_path / "releases" / tag / "safe.jsonl.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    catalog_sha = "a" * 64

    first = module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
    )
    assert first["materialization_complete"] is True
    assert first["registry_reused_shards"] == 0

    database = destination / "SAFE_SHARDS.sqlite3"
    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT validation_owner, quality_status, replayable, backtestable, "
            "catalog_active, sha256 FROM safe_shards WHERE dataset_id = ?",
            (row["dataset_id"],),
        ).fetchone()
        current_count = connection.execute(
            "SELECT COUNT(*) FROM current_safe_shards"
        ).fetchone()[0]
        run_status = connection.execute(
            "SELECT value FROM safe_shard_registry_meta WHERE key = 'run_status'"
        ).fetchone()[0]
    assert stored == ("ALINA_SYNC", "SAFE", 1, 1, 1, digest)
    assert current_count == 1
    assert run_status == "COMPLETE"

    def forbidden_hash(_path):
        raise AssertionError("an unchanged AlinaSync-validated shard was re-hashed")

    monkeypatch.setattr(module, "_sha256", forbidden_hash)
    second = module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
    )
    assert second["materialization_complete"] is True
    assert second["registry_reused_shards"] == 1
    assert second["skipped_verified_shards"] == 1

    next_catalog_sha = "c" * 64
    third = module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=next_catalog_sha,
    )
    assert third["registry_reused_shards"] == 1
    assert third["registry_recorded_shards"] == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT catalog_sha256, catalog_active FROM safe_shards "
            "WHERE dataset_id = ?",
            (row["dataset_id"],),
        ).fetchone() == (next_catalog_sha, 1)


def test_alinasync_registry_never_reuses_a_changed_shard(tmp_path, monkeypatch):
    module = _module()
    payload = gzip.compress(b'{"trade_id":"safe"}\n', mtime=0)
    digest = hashlib.sha256(payload).hexdigest()
    tag = "data-v2-durable-safe-state-change"
    row = {
        "dataset_id": "safe-durable-changed",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "validation_allowed": True,
        "asset_verified": True,
        "release_tag": tag,
        "release_asset": "safe.jsonl.gz",
        "bytes": len(payload),
        "sha256": digest,
    }
    destination = tmp_path / "restore"
    source = tmp_path / "releases" / tag / "safe.jsonl.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    catalog_sha = "b" * 64
    first = module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
    )
    assert first["materialization_complete"] is True

    target = destination / "usable" / "shards" / tag / "safe-durable-changed.jsonl.gz"
    target.unlink()
    target.write_bytes(b"x" * len(payload))
    checked = 0
    original = module._verified_row_bytes

    def counted(path, expected):
        nonlocal checked
        checked += 1
        return original(path, expected)

    monkeypatch.setattr(module, "_verified_row_bytes", counted)
    second = module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
    )
    assert checked >= 1
    assert second["registry_reused_shards"] == 0
    assert second["materialization_complete"] is True
    assert target.read_bytes() == payload


def test_alinasync_registry_hides_safe_rows_during_incomplete_revalidation(tmp_path):
    import sqlite3

    module = _module()
    payload = gzip.compress(b'{"trade_id":"safe"}\n', mtime=0)
    digest = hashlib.sha256(payload).hexdigest()
    tag = "data-v2-registry-incomplete"
    row = {
        "dataset_id": "safe-before-failure",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "validation_allowed": True,
        "asset_verified": True,
        "release_tag": tag,
        "release_asset": "safe.jsonl.gz",
        "bytes": len(payload),
        "sha256": digest,
    }
    destination = tmp_path / "restore"
    source = tmp_path / "releases" / tag / "safe.jsonl.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    catalog_sha = "d" * 64
    assert module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
    )["materialization_complete"] is True

    target = destination / "usable" / "shards" / tag / "safe-before-failure.jsonl.gz"
    target.unlink()
    source.unlink()
    failed = module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
    )
    assert failed["materialization_complete"] is False
    with sqlite3.connect(destination / "SAFE_SHARDS.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM current_safe_shards"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT value FROM safe_shard_registry_meta WHERE key = 'run_status'"
        ).fetchone()[0] == "IN_PROGRESS"
        assert connection.execute(
            "SELECT COUNT(*) FROM safe_shards"
        ).fetchone()[0] == 1


def test_incomplete_staged_subset_does_not_invalidate_completed_registry(tmp_path):
    import sqlite3

    module = _module()
    payload = gzip.compress(b'{"trade_id":"safe"}\n', mtime=0)
    tag = "data-v2-registry-staged"
    row = {
        "dataset_id": "safe-complete",
        "quality_status": "SAFE",
        "replay_compatible": True,
        "validation_allowed": True,
        "asset_verified": True,
        "release_tag": tag,
        "release_asset": "safe.jsonl.gz",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    destination = tmp_path / "restore"
    source = tmp_path / "releases" / tag / "safe.jsonl.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    catalog_sha = "e" * 64
    assert module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
    )["materialization_complete"] is True

    staged_row = {
        **row,
        "dataset_id": "safe-missing-staged",
        "release_asset": "missing.jsonl.gz",
    }
    failed = module._materialize_catalog_safe_shards(
        [staged_row], tmp_path / "releases", destination,
        prune_stale=False, catalog_sha256=catalog_sha,
        authoritative_registry=False,
    )
    assert failed["materialization_complete"] is False
    with sqlite3.connect(destination / "SAFE_SHARDS.sqlite3") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM current_safe_shards"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT value FROM safe_shard_registry_meta WHERE key = 'run_status'"
        ).fetchone()[0] == "COMPLETE"


def test_materialize_safe_shards_prepares_each_release_root_once(
    tmp_path, monkeypatch,
):
    module = _module()
    destination = tmp_path / "restore"
    tag = "data-v2-shared-root"
    target_root = destination / "usable" / "shards" / tag
    target_root.mkdir(parents=True)
    for index in range(12):
        (target_root / f"safe-{index}.jsonl.gz").write_bytes(b"x")
    calls = 0
    original_windows_io_path = module._windows_io_path

    def counted_windows_io_path(path):
        nonlocal calls
        if Path(path) == target_root:
            calls += 1
        return original_windows_io_path(path)

    monkeypatch.setattr(module, "_windows_io_path", counted_windows_io_path)
    monkeypatch.setattr(module, "_verified_row_bytes", lambda *_args: True)
    rows = [
        {
            "dataset_id": f"safe-{index}",
            "release_tag": tag,
            "release_asset": "source.jsonl.gz",
            "bytes": 1,
            "sha256": hashlib.sha256(b"x").hexdigest(),
        }
        for index in range(12)
    ]

    result = module._materialize_catalog_safe_shards(
        rows, tmp_path / "releases", destination, prune_stale=False,
    )

    assert result["materialization_complete"] is True
    assert calls <= 3


def test_materialize_rechecks_usable_ancestor_immediately_before_write(
    tmp_path, monkeypatch,
):
    module = _module()
    destination = tmp_path / "restore"
    usable = destination / "usable"
    verification_finished = False
    original_is_symlink = Path.is_symlink

    def missing_target(_path, _row):
        nonlocal verification_finished
        verification_finished = True
        return False

    def late_usable_symlink(path):
        if verification_finished and Path(path) == module._windows_io_path(usable):
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(module, "_verified_row_bytes", missing_target)
    monkeypatch.setattr(Path, "is_symlink", late_usable_symlink)
    row = {
        "dataset_id": "safe-late-link", "release_tag": "data-v2-late-link",
        "release_asset": "source.jsonl.gz", "bytes": 1,
        "sha256": hashlib.sha256(b"x").hexdigest(),
    }

    result = module._materialize_catalog_safe_shards(
        [row], tmp_path / "releases", destination, prune_stale=False,
    )

    assert result["failures"] == [{
        "dataset_id": "safe-late-link", "error": "SYMLINKED_SHARD_DIRECTORY",
    }]


def test_pending_materialization_bytes_are_computed_concurrently(
    tmp_path, monkeypatch,
):
    import threading
    import time

    module = _module()
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def slow_verified(_path, row):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return int(row["bytes"]) % 2 == 0

    monkeypatch.setattr(module, "_verified_row_bytes", slow_verified)
    rows = [
        {
            "dataset_id": f"safe-{index}",
            "release_tag": "data-v2-parallel-plan",
            "release_asset": "bundle.zip",
            "release_container_asset": "bundle.zip",
            "bytes": index,
            "sha256": hashlib.sha256(str(index).encode()).hexdigest(),
        }
        for index in range(1, 13)
    ]

    pending = module._pending_catalog_materialization_bytes(
        rows, tmp_path / "restore",
    )

    assert pending == sum(range(1, 13, 2))
    assert maximum_active >= 2


def test_unlimited_replay_uses_conservative_preflight_without_sha_rescan():
    module = _module()
    rows = [
        {"release_container_asset": "bundle.zip", "bytes": 30},
        {"release_container_asset": "bundle.zip", "bytes": 20},
        {"bytes": 999},
    ]

    plan = module._conservative_replay_preflight(
        rows,
        source_asset_bytes=100,
        free_destination=2 * 1024 * 1024 * 1024,
        max_download_bytes=None,
    )

    assert plan == {
        "pending_download_bytes": 100,
        "pending_retained_download_bytes": 100,
        "peak_staged_asset_bytes": 0,
        "pending_materialization_bytes": 50,
        "required_free_destination_bytes": 100 + 50 + 1024 * 1024 * 1024,
    }


def test_conservative_preflight_falls_back_for_cap_or_insufficient_disk():
    module = _module()
    rows = [{"release_container_asset": "bundle.zip", "bytes": 30}]

    assert module._conservative_replay_preflight(
        rows, source_asset_bytes=100, free_destination=2**40,
        max_download_bytes=99,
    ) is None
    assert module._conservative_replay_preflight(
        rows, source_asset_bytes=100, free_destination=10,
        max_download_bytes=None,
    ) is None


def test_long_target_root_symlink_check_uses_windows_io_path(
    tmp_path, monkeypatch,
):
    module = _module()
    payload = b'{"trade_id":"long-symlink-root"}\n'
    tag = "data-v2-long-symlink-root"
    releases_root = tmp_path / "releases"
    source = releases_root / tag / "source.jsonl.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    destination = tmp_path / "restore"
    display_root = destination / "usable" / "shards" / tag
    io_root = tmp_path / "extended-io-root"
    original_windows_io_path = module._windows_io_path
    original_is_symlink = Path.is_symlink

    def redirect_target_root(path):
        path = Path(path)
        if path == display_root:
            return io_root
        return original_windows_io_path(path)

    def mark_io_root_as_symlink(path):
        if path == io_root:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(module, "_windows_io_path", redirect_target_root)
    monkeypatch.setattr(Path, "is_symlink", mark_io_root_as_symlink)
    row = {
        "dataset_id": "safe-long-root",
        "release_tag": tag,
        "release_asset": source.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    result = module._materialize_catalog_safe_shards(
        [row], releases_root, destination, prune_stale=False,
    )

    assert result["failures"] == [{
        "dataset_id": "safe-long-root",
        "error": "SYMLINKED_SHARD_DIRECTORY",
    }]
    assert not io_root.exists()


def test_stale_symlink_check_uses_windows_io_path(tmp_path, monkeypatch):
    module = _module()
    destination = tmp_path / "restore"
    previous = destination / "usable" / "shards" / "old" / "old.jsonl.gz"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"stale")
    io_previous = module._windows_io_path(previous)
    original_is_symlink = Path.is_symlink

    def mark_io_previous_as_symlink(path):
        if path == io_previous:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", mark_io_previous_as_symlink)

    result = module._materialize_catalog_safe_shards(
        [], tmp_path / "releases", destination, prune_stale=True,
    )

    assert result["failures"] == [{
        "path": str(previous),
        "error": "SYMLINKED_STALE_SHARD_NOT_PRUNED",
    }]
    assert previous.read_bytes() == b"stale"


@pytest.mark.skipif(os.name != "nt", reason="Windows long-path regression")
def test_stale_long_materialized_shard_uses_windows_io_paths(tmp_path):
    module = _module()
    payload = b'{"trade_id":"stale-long-windows-path"}\n'
    tag = "data-v2-long-stale"
    dataset_id = "safe-" + ("x" * 210)
    releases_root = tmp_path / "releases"
    source = releases_root / tag / "source.jsonl.gz"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    destination = tmp_path / "restore"
    row = {
        "dataset_id": dataset_id,
        "release_tag": tag,
        "release_asset": source.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    created = module._materialize_catalog_safe_shards(
        [row], releases_root, destination, prune_stale=False,
    )
    target = (
        destination / "usable" / "shards" / tag
        / f"{module._safe_component(dataset_id)}.jsonl.gz"
    )
    assert len(str(target)) > 260
    assert created["materialization_complete"] is True
    assert module._windows_io_path(target).read_bytes() == payload

    pruned = module._materialize_catalog_safe_shards(
        [], releases_root, destination, prune_stale=True,
    )

    assert pruned["failures"] == []
    assert pruned["materialization_complete"] is True
    assert pruned["stale_usable_quarantined"] == 1
    assert not module._windows_io_path(target).exists()
    quarantined = list(
        module._windows_io_path(
            destination / "quarantine" / "stale_usable" / tag
        ).glob("*.stale")
    )
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == payload


def test_restore_zip_rejects_casefold_collisions_but_accepts_safe_nested_files(tmp_path):
    import pytest

    module = _module()
    archive_path = tmp_path / "casefold.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Trades/BTC.jsonl.gz", b"a")
        archive.writestr("trades/btc.jsonl.gz", b"b")
    with pytest.raises(module.RestoreError, match="duplicate ZIP members"):
        module._verify_zip_archive(archive_path, archive_path.name)

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe/BTC.jsonl.gz", b"a")
        archive.writestr("safe/ETH.jsonl.gz", b"b")
    module._verify_zip_archive(archive_path, archive_path.name)


def _lfs_fixture(tmp_path, payload, *, release_tag="data-v2-lfs"):
    """Small real-byte Git LFS worktree with an immutable Release identity."""
    asset = _asset("source.jsonl.gz", "https://example.invalid/source", payload)
    asset.update({"id": 7, "state": "uploaded"})
    release = {"id": 91, "tag_name": release_tag, "assets": [asset]}
    rel = f"clone_payload/releases/{release_tag}/7--source.jsonl.gz"
    source = tmp_path / rel
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    manifest = {
        "schema": "alina.clone_payload_manifest.v1",
        "repository": "owner/repo",
        "entries": [{
            "asset_id": 7, "release_id": 91,
            "release_tag": release_tag, "asset_name": asset["name"],
            "clone_path": rel, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }],
        "total_assets": 1, "total_bytes": len(payload),
    }
    path = tmp_path / "clone_payload" / "MANIFEST.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return release, source, path


def test_restore_reuses_exact_lfs_bytes_without_redownloading(tmp_path, monkeypatch):
    module = _module()
    payload = b"verified-bytes-in-git-lfs"
    release, source, _ = _lfs_fixture(tmp_path, payload, release_tag="evidence-lfs")
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([release]))
    monkeypatch.setattr(module, "_download_to_path",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            AssertionError("verified LFS must not download")))
    output = tmp_path / "restored"
    report = module.restore_everything("owner/repo", output, clone_root=tmp_path)
    assert report["lfs_reused_verified"] == 1
    assert report["downloaded"] == 0
    assert report["all_source_assets_accounted_for"] is True
    assert (output / "releases" / "evidence-lfs" / "source.jsonl.gz").read_bytes() == payload
    assert source.read_bytes() == payload


def test_restore_corrupt_lfs_falls_back_to_verified_release(tmp_path, monkeypatch):
    module = _module()
    payload = b"correct-release-payload"
    release, source, _ = _lfs_fixture(tmp_path, payload, release_tag="evidence-lfs")
    source.write_bytes(b"damaged-lfs-payload")
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([release]))
    calls = []
    def download(_url, target, **_k):
        calls.append(_url)
        target.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(module, "_download_to_path", download)
    report = module.restore_everything(
        "owner/repo", tmp_path / "restored", clone_root=tmp_path,
    )
    assert calls == ["https://example.invalid/source"]
    assert report["downloaded"] == 1
    assert report["lfs_reused_verified"] == 0
    assert source.read_bytes() == b"damaged-lfs-payload"


def test_restore_never_trusts_stale_lfs_release_identity(tmp_path, monkeypatch):
    module = _module()
    payload = b"remote-is-authoritative"
    release, _, path = _lfs_fixture(tmp_path, payload, release_tag="evidence-lfs")
    manifest = json.loads(path.read_text())
    manifest["entries"][0]["release_id"] = 999
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([release]))
    calls = []
    def download(url, target, **_k):
        calls.append(url)
        target.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(module, "_download_to_path", download)
    report = module.restore_everything("owner/repo", tmp_path / "restored",
                                       clone_root=tmp_path)
    assert report["lfs_reused_verified"] == 0
    assert report["downloaded"] == 1
    assert len(calls) == 1


def test_restore_rejects_unsafe_lfs_mirror_paths_before_transfer(tmp_path, monkeypatch):
    import pytest
    module = _module()
    release, _, path = _lfs_fixture(tmp_path, b"source", release_tag="evidence-lfs")
    manifest = json.loads(path.read_text())
    manifest["entries"][0]["clone_path"] = "clone_payload/releases/../../outside"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([release]))
    monkeypatch.setattr(module, "_download_to_path",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            AssertionError("must not download unsafe paths")))
    with pytest.raises(module.RestoreError, match="unsafe Git LFS clone asset path"):
        module.restore_everything("owner/repo", tmp_path / "restored",
                                  clone_root=tmp_path)


def test_restore_rejects_duplicate_lfs_asset_ids(tmp_path):
    import pytest
    module = _module()
    release, _, path = _lfs_fixture(tmp_path, b"source")
    manifest = json.loads(path.read_text())
    manifest["entries"].append(dict(manifest["entries"][0]))
    manifest["total_assets"] = 2
    manifest["total_bytes"] *= 2
    path.write_text(json.dumps(manifest))
    with pytest.raises(module.RestoreError, match="duplicate or invalid Git LFS asset id"):
        module._clone_lfs_sources(tmp_path, "owner/repo", [release])


def test_restore_verified_overflow_via_canonical_manifest(tmp_path, monkeypatch):
    module = _module()
    shard = b"verified-overflow-bytes"
    digest = hashlib.sha256(shard).hexdigest()
    data_tag, control_tag = "data-v2-overflow-test", "data-v2-overflow-test-manifest"
    row = {
        "dataset_id": "overflow-trade-1", "quality_status": "SAFE",
        "validation_allowed": True, "replay_compatible": True,
        "asset_verified": True, "bytes": len(shard), "sha256": digest,
        "release": {"repository": "owner/repo", "release_tag": data_tag,
                    "asset_name": "trades.jsonl.gz"},
    }
    canonical = {
        "schema": "alina.dataset_run_manifest.v2",
        "release_tag": control_tag,
        "release_parts": [{"release_tag": data_tag}],
        "manifests": [row],
    }
    body = json.dumps(canonical).encode("utf-8")
    releases = [
        {"tag_name": data_tag, "assets": [
            _asset("trades.jsonl.gz", "https://example.invalid/trades", shard)]},
        {"tag_name": control_tag, "assets": [
            _asset("RUN_MANIFEST.json", "https://example.invalid/manifest", body)]},
    ]
    data = {"https://example.invalid/trades": shard,
            "https://example.invalid/manifest": body}
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter(releases))
    def fake_download(url, target, **_kw):
        payload = data[url]
        target.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(module, "_download_to_path", fake_download)
    index = tmp_path / "DATA_INDEX.json"
    index.write_text(json.dumps({"shards": [{
        "dataset_id": row["dataset_id"], "sha256": digest,
        "quality_status": "SAFE", "replay_compatible": True,
        "validation_allowed": True, "asset_verified": True,
        "release_tag": data_tag,
    }]}))
    metrics = tmp_path / "DATA_METRICS.json"
    metrics.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 1},
    }))
    result = module.restore_everything(
        "owner/repo", tmp_path / "recovered",
        catalog_path=index, metrics_path=metrics,
    )
    assert result["unclaimed_dataset_release_count"] == 0
    assert result["verification_failures"] == 0
    assert result["classification"]["usable_shards"] == 1
    assert result["classification"]["missing_or_corrupt_rows"] == 0
    assert result["failures"] == []
    assert (tmp_path / "recovered" / "usable" / "shards" /
            data_tag / "overflow-trade-1.jsonl.gz").read_bytes() == shard


def test_release_pagination_uses_max_pages_and_enumerates_every_release(monkeypatch):
    module = _module()
    urls = []
    def fetch_json(url, **_kwargs):
        urls.append(url)
        if "releases?" not in url:
            raise AssertionError(url)
        size = int(url.split("per_page=")[1].split("&")[0])
        page = int(url.rsplit("page=", 1)[1])
        return [
            {"id": n + 1, "tag_name": f"release-{n + 1}", "assets": []}
            for n in range((page - 1) * size, min(page * size, 203))
        ]
    monkeypatch.setattr(module, "_json", fetch_json)
    monkeypatch.setattr(module, "_list_release_assets", lambda *_a, **_k: [])
    result = list(module.iter_releases("owner/repo"))
    assert len(result) == 203
    assert len({x["id"] for x in result}) == 203
    assert len(urls) == 3
    assert all("per_page=100" in url for url in urls)


def test_snapshot_segment_copy_is_exact_and_bounded():
    module = _module()
    source_payload = b"segment-payload" * 700000  # > 8 MiB
    class MeasuredSource(io.BytesIO):
        largest_request = 0
        def read(self, size=-1):
            assert 0 < size <= 8 * 1024 * 1024
            self.largest_request = max(self.largest_request, size)
            return super().read(size)

    source = MeasuredSource(source_payload)
    output = io.BytesIO()
    module._copy_exact_segment(source, output, len(source_payload) - 3)
    assert output.getvalue() == source_payload[:-3]
    assert source.tell() == len(source_payload) - 3
    assert source.largest_request == 8 * 1024 * 1024


def test_snapshot_segment_copy_refuses_short_source_without_padding():
    import pytest
    module = _module()
    output = io.BytesIO()
    with pytest.raises(module.RestoreError, match="short chunk read"):
        module._copy_exact_segment(io.BytesIO(b"abc"), output, 7)
    assert output.getvalue() == b"abc"


def test_restore_uses_exact_embedded_asset_inventory(monkeypatch):
    module = _module()
    one = {**_asset("one.bin", "https://example.invalid/one", b"one"),
           "id": 77, "state": "uploaded"}
    two = {**_asset("two.bin", "https://example.invalid/two", b"two"),
           "id": 78, "state": "uploaded"}
    urls = []
    def fake_json(url, **_kwargs):
        urls.append(url)
        if "/releases?" in url:
            return [{"id": 3, "tag_name": "archive-3", "assets": [one, two]}]
        raise AssertionError(url)
    monkeypatch.setattr(module, "_json", fake_json)
    rows = list(module.iter_releases("owner/repo"))
    assert len(rows) == 1
    assert rows[0]["assets"] == [one, two]
    assert len(urls) == 1


def test_restore_rejects_duplicate_embedded_asset_name(monkeypatch):
    import pytest
    module = _module()
    one = {**_asset("one.bin", "https://example.invalid/one", b"one"),
           "id": 77, "state": "uploaded"}
    duplicate = dict(one, id=78)
    monkeypatch.setattr(module, "_json", lambda *_a, **_k: [
        {"id": 3, "tag_name": "archive-3", "assets": [one, duplicate]}
    ])
    with pytest.raises(module.RestoreError, match="duplicated asset name"):
        list(module.iter_releases("owner/repo"))


def test_restore_rate_limit_fails_fast_with_resume_hint(monkeypatch, tmp_path):
    import io
    import urllib.error
    module = _module()
    calls = []
    def quota_exhausted(request, **_kwargs):
        calls.append(request)
        raise urllib.error.HTTPError(
            "https://api.github.com/example", 403, "rate limit",
            {"X-RateLimit-Remaining": "0"}, io.BytesIO(b"rate limit"),
        )
    monkeypatch.setattr(module.urllib.request, "urlopen", quota_exhausted)
    with pytest.raises(module.RestoreError, match="rate limit exhausted"):
        module._request("https://api.github.com/example")
    assert len(calls) == 1
    calls.clear()
    with pytest.raises(module.RestoreError, match="rate limit exhausted"):
        module._download_to_path("https://api.github.com/example", tmp_path / "part.partial")
    assert len(calls) == 1


def test_restore_refuses_unverified_short_embedded_release_asset(monkeypatch):
    module = _module()
    asset = {**_asset("one.bin", "https://example.invalid/one", b"one"),
             "id": 77, "state": "uploaded", "digest": None}
    monkeypatch.setattr(module, "_json", lambda *_a, **_k: [
        {"id": 3, "tag_name": "archive-3", "assets": [asset]}
    ])
    import pytest
    with pytest.raises(module.RestoreError, match="SHA-256"):
        list(module.iter_releases("owner/repo"))


def test_failed_release_asset_never_reports_all_bytes_accounted_for(tmp_path, monkeypatch):
    module = _module()
    expected = b"canonical-verified-evidence"
    release = {"tag_name": "evidence-incomplete", "assets": [
        _asset("evidence.bin", "https://example.invalid/evidence", expected),
    ]}
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([release]))

    def incomplete_download(_url, target, **_kw):
        target.write_bytes(expected[:6])
        return 6, hashlib.sha256(expected[:6]).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", incomplete_download)
    report = module.restore_everything("owner/repo", tmp_path)
    assert report["expected_assets"] == 1
    assert report["asset_count"] == 1
    assert report["downloaded"] == 0
    assert len(report["failures"]) == 1
    assert report["all_source_assets_accounted_for"] is False
    assert report["source_asset_bytes"] == len(expected)
    assert report["verified_asset_bytes"] == 0
    assert report["missing_asset_bytes"] == len(expected)
    assert report["corrupt_volume_bytes"] == 6
    assert report["failed_verification_source_bytes"] == len(expected)
    assert report["source_byte_parity"] is False
    assert not (tmp_path / "releases" / "evidence-incomplete" / "evidence.bin").exists()


def test_local_snapshot_refuses_case_insensitive_target_collision_before_writing(tmp_path):
    import pytest
    module = _module()
    releases = tmp_path / "releases"
    release = releases / "alina-local-snapshot-20990101T000000Z"
    release.mkdir(parents=True)
    raw = b"immutable-snapshot"
    chunk = release / "ALINA_LOCAL_SNAPSHOT.chunk0000.bin"
    chunk.write_bytes(raw)
    row = {
        "path": "runtime/Trade.bin",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "segments": [{"chunk": chunk.name, "offset": 0, "bytes": len(raw)}],
    }
    (release / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps({
            "schema": "alina.local_snapshot.v1",
            "chunks": [{"name": chunk.name, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()}],
            "files": [row, {**row, "path": "runtime/trade.bin"}],
        }), encoding="utf-8",
    )
    workspace = tmp_path / "fresh-clone"
    workspace.mkdir()
    with pytest.raises(module.RestoreError, match="duplicate or unsafe local snapshot target"):
        module.materialize_latest_local_snapshot(releases, workspace)
    assert not (workspace / "runtime" / "Trade.bin").exists()
    assert not (workspace / "runtime" / "trade.bin").exists()

def test_resumed_download_refuses_unmatched_content_range_without_touching_prefix(tmp_path, monkeypatch):
    import pytest
    module = _module()
    target = tmp_path / "asset.partial"
    target.write_bytes(b"prefix-")

    class Response:
        status = 206
        headers = {"Content-Range": "bytes 0-5/13"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b"suffix"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_a, **_k: Response())
    with pytest.raises(module.RestoreError, match="Content-Range"):
        module._download_to_path("https://example.invalid/asset", target)
    assert target.read_bytes() == b"prefix-"


def test_resumed_download_refuses_missing_content_range(tmp_path, monkeypatch):
    import pytest
    module = _module()
    target = tmp_path / "asset.partial"
    target.write_bytes(b"prefix-")

    class Response:
        status = 206
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b"suffix"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_a, **_k: Response())
    with pytest.raises(module.RestoreError, match="Content-Range"):
        module._download_to_path("https://example.invalid/asset", target)
    assert target.read_bytes() == b"prefix-"


def test_streaming_download_retries_http_incomplete_read(tmp_path, monkeypatch):
    module = _module()
    calls = []

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            if hasattr(self, "done"):
                return b""
            self.done = True
            return b"complete"

    def urlopen(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise module.http.client.IncompleteRead(b"", 1)
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda *_a: None)
    destination = tmp_path / "asset.partial"
    size, sha = module._download_to_path("https://example.invalid/asset", destination)
    assert len(calls) == 2
    assert destination.read_bytes() == b"complete"
    assert size == 8 and sha == hashlib.sha256(b"complete").hexdigest()


def test_recovery_rejects_symlinked_release_asset_and_partial(tmp_path):
    module = _module()
    victim = tmp_path / "outside.bin"
    victim.write_bytes(b"do-not-overwrite")
    directory = tmp_path / "releases"
    directory.mkdir()
    asset = _asset("asset.bin", "https://example.invalid/asset", b"safe")

    target = directory / "asset.bin"
    _create_symlink_or_skip(target, victim)
    with pytest.raises(module.RestoreError, match="symlinked Release asset target"):
        module.download_asset(asset, directory)
    target.unlink()

    partial = directory / "asset.bin.partial"
    _create_symlink_or_skip(partial, victim)
    with pytest.raises(module.RestoreError, match="symlinked Release asset partial"):
        module.download_asset(asset, directory)
    assert victim.read_bytes() == b"do-not-overwrite"

def test_restore_rejects_symlinked_release_storage_directory(tmp_path):
    module = _module()
    external = tmp_path / "external"
    external.mkdir()
    destination = tmp_path / "restore"
    destination.mkdir()
    _create_symlink_or_skip(
        destination / "releases", external, target_is_directory=True
    )
    with pytest.raises(module.RestoreError, match="symlinked Release storage"):
        module.restore_everything("owner/repo", destination)
    assert list(external.iterdir()) == []


def test_restore_retains_atomic_failure_report_for_bad_local_snapshot(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([]))

    def fail_snapshot(*_a, **_kw):
        raise module.RestoreError("bad local snapshot segment")

    monkeypatch.setattr(module, "materialize_latest_local_snapshot", fail_snapshot)
    result = module.restore_everything("owner/repo", tmp_path, workspace=tmp_path)
    assert result["status"] == "RESTORE_INCOMPLETE"
    assert result["all_source_assets_accounted_for"] is True
    assert result["local_snapshot"]["status"] == "FAIL"
    assert result["failures"][0]["stage"] == "local_snapshot"
    report_path = tmp_path / "RESTORE_REPORT.json"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "RESTORE_INCOMPLETE"
    assert not (tmp_path / "RESTORE_REPORT.json.partial").exists()


def test_restore_rejects_case_insensitive_release_tag_collision_before_transfer(tmp_path, monkeypatch):
    import pytest
    module = _module()
    releases = [
        {"tag_name": "alina-Data", "assets": []},
        {"tag_name": "alina-data", "assets": []},
    ]
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter(releases))
    monkeypatch.setattr(module, "download_asset", lambda *_a, **_kw: (_ for _ in ()).throw(
        AssertionError("colliding releases must never be downloaded")
    ))
    with pytest.raises(module.RestoreError, match="case-insensitive Release directory collision"):
        module.restore_everything("owner/repo", tmp_path)


def test_restore_rejects_case_insensitive_asset_collision_before_transfer(tmp_path, monkeypatch):
    import pytest
    module = _module()
    release = {
        "tag_name": "safe-release", "assets": [
            _asset("Trades.jsonl.gz", "https://example.invalid/upper", b"first"),
            _asset("trades.jsonl.gz", "https://example.invalid/lower", b"second"),
        ],
    }
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([release]))
    monkeypatch.setattr(module, "download_asset", lambda *_a, **_kw: (_ for _ in ()).throw(
        AssertionError("colliding assets must never be downloaded")
    ))
    with pytest.raises(module.RestoreError, match="case-insensitive asset name collision"):
        module.restore_everything("owner/repo", tmp_path)


def test_explicit_missing_local_snapshot_fails_closed_and_writes_report(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([]))
    report = module.restore_everything("owner/repo", tmp_path, workspace=tmp_path)
    assert report["status"] == "RESTORE_INCOMPLETE"
    assert report["local_snapshot"]["status"] == "FAIL"
    assert "no verified local snapshot" in report["local_snapshot"]["error"]
    assert report["all_source_assets_accounted_for"] is True
    assert report["failures"] == [{
        "stage": "local_snapshot",
        "error": "no verified local snapshot available to materialize",
    }]
    persisted = json.loads((tmp_path / "RESTORE_REPORT.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "RESTORE_INCOMPLETE"


def test_local_snapshot_failure_cannot_mark_certified_restore_complete(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([]))
    monkeypatch.setattr(module, "materialize_latest_local_snapshot",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            module.RestoreError("snapshot checksum failed")))
    report = module.restore_everything(
        "owner/repo", tmp_path, workspace=tmp_path,
    )
    assert report["status"] == "RESTORE_INCOMPLETE"
    assert report["failures"][0]["stage"] == "local_snapshot"
def test_restore_cli_refuses_asset_only_success(tmp_path, monkeypatch, capsys):
    """Verified downloads are not a certified catalog-bound SAFE restore."""
    module = _module()
    report = {
        "status": "ASSETS_VERIFIED_ONLY",
        "source_inventory_sha256": "a" * 64,
        "release_count": 1,
        "asset_count": 1,
        "downloaded": 1,
        "resumed_verified": 0,
        "skipped_verified": 0,
        "lfs_reused_verified": 0,
        "classification": {
            "usable_shards": 0, "quarantined_shards": 0,
            "missing_or_corrupt_rows": 0, "failures": [],
        },
        "failures": [],
        "verification_failures": 0,
        "unclaimed_dataset_release_count": 0,
        "all_source_assets_accounted_for": True,
    }
    monkeypatch.setattr(module, "restore_everything", lambda *_a, **_kw: report)
    exit_code = module.main(["--everything", "--destination", str(tmp_path)])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert result["status"] == "FAIL"
    assert result["restoration_status"] == "ASSETS_VERIFIED_ONLY"
    assert result["failures"] >= 1


def test_restore_cli_handles_filesystem_failure_without_traceback(
    tmp_path, monkeypatch, capsys,
):
    module = _module()

    def disk_failure(*_args, **_kwargs):
        raise OSError("destination disk unavailable")

    monkeypatch.setattr(module, "restore_everything", disk_failure)
    assert module.main(["--everything", "--destination", str(tmp_path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "ALINA_RESTORE_FAIL: destination disk unavailable" in output.err
    assert "Traceback" not in output.err


def test_restore_local_snapshot_does_not_revive_stale_cached_release(tmp_path, monkeypatch):
    """Removed Releases cannot materialize ignored workspace files from old cache."""
    module = _module()
    root = tmp_path / "restore"
    stale = root / "releases" / "alina-local-snapshot-stale"
    stale.mkdir(parents=True)
    content = b"not-in-current-source-inventory"
    chunk = stale / "ALINA_LOCAL_SNAPSHOT.chunk0000.bin"
    chunk.write_bytes(content)
    (stale / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps({
            "schema": "alina.local_snapshot.v1", "tag": stale.name,
            "chunks": [{
                "name": chunk.name, "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }],
            "files": [{
                "path": "runtime/ignored-old.bin", "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "segments": [{"chunk": chunk.name, "offset": 0, "bytes": len(content)}],
            }],
        }), encoding="utf-8",
    )
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([]))
    workspace = tmp_path / "fresh-clone"
    workspace.mkdir()
    report = module.restore_everything(
        "owner/repo", root, workspace=workspace,
    )
    assert report["status"] == "RESTORE_INCOMPLETE"
    assert report["local_snapshot"]["status"] == "FAIL"
    assert not (workspace / "runtime" / "ignored-old.bin").exists()


def test_restore_local_snapshot_accepts_current_release_only(tmp_path):
    module = _module()
    releases = tmp_path / "releases"
    cached = releases / "alina-local-snapshot-cached"
    current = releases / "alina-local-snapshot-current"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for directory, payload in ((cached, b"old"), (current, b"current")):
        directory.mkdir(parents=True)
        name = "ALINA_LOCAL_SNAPSHOT.chunk0000.bin"
        (directory / name).write_bytes(payload)
        (directory / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
            json.dumps({
                "schema": "alina.local_snapshot.v1", "tag": directory.name,
                "created_at_utc": "9999-01-01" if directory == cached else "2026-10-11",
                "chunks": [{
                    "name": name, "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }],
                "files": [{
                    "path": "runtime/restored.bin", "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "segments": [{
                        "chunk": name, "offset": 0, "bytes": len(payload),
                    }],
                }],
            }), encoding="utf-8",
        )
    result = module.materialize_latest_local_snapshot(
        releases, workspace, allowed_release_dirs={current.name},
    )
    assert result["tag"] == current.name
    assert (workspace / "runtime" / "restored.bin").read_bytes() == b"current"


def test_restore_rejects_duplicate_snapshot_chunks_and_git_case_alias(tmp_path):
    import pytest

    module = _module()
    with pytest.raises(module.RestoreError, match="inside .git"):
        module._safe_workspace_target(tmp_path, ".GIT/config")

    releases = tmp_path / "releases"
    directory = releases / "alina-local-snapshot-duplicate"
    directory.mkdir(parents=True)
    name = "ALINA_LOCAL_SNAPSHOT.chunk0000.bin"
    payload = b"present"
    (directory / name).write_bytes(payload)
    row = {
        "name": name, "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    (directory / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps({
            "schema": "alina.local_snapshot.v1",
            "tag": directory.name, "chunks": [row, dict(row)], "files": [],
        }), encoding="utf-8",
    )
    with pytest.raises(module.RestoreError, match="duplicate local snapshot chunk"):
        module.materialize_latest_local_snapshot(
            releases, tmp_path, allowed_release_dirs={directory.name},
        )


def test_restore_snapshot_rejects_foreign_repository_provenance(tmp_path):
    import pytest

    module = _module()
    releases = tmp_path / "releases"
    release = releases / "alina-local-snapshot-current"
    release.mkdir(parents=True)
    (release / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps({
            "schema": "alina.local_snapshot.v1", "tag": release.name,
            "repository": "other-owner/other-repo", "chunks": [], "files": [],
        }), encoding="utf-8",
    )
    with pytest.raises(module.RestoreError, match="source repository mismatch"):
        module.materialize_latest_local_snapshot(
            releases, tmp_path, allowed_release_dirs={release.name},
            repository="owner/repo",
        )


def test_restore_snapshot_end_to_end_only_from_current_repository(tmp_path, monkeypatch):
    module = _module()
    release_tag = "alina-local-snapshot-current"
    data = b"recover-this-evidence"
    part_name = "ALINA_LOCAL_SNAPSHOT.chunk0000.bin"
    index_name = "ALINA_LOCAL_SNAPSHOT_INDEX.json"
    index = json.dumps({
        "schema": "alina.local_snapshot.v1",
        "tag": release_tag, "repository": "owner/repo",
        "chunks": [{
            "name": part_name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }],
        "files": [{
            "path": "runtime/restored-evidence.bin",
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "segments": [{"chunk": part_name, "offset": 0, "bytes": len(data)}],
        }],
    }).encode()
    source = {
        "https://example.invalid/part": data,
        "https://example.invalid/index": index,
    }
    release = {"tag_name": release_tag, "assets": [
        _asset(part_name, "https://example.invalid/part", data),
        _asset(index_name, "https://example.invalid/index", index),
    ]}
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([release]))
    def fake_download(url, target, **_kwargs):
        target.write_bytes(source[url])
        return len(source[url]), hashlib.sha256(source[url]).hexdigest()
    monkeypatch.setattr(module, "_download_to_path", fake_download)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = module.restore_everything(
        "owner/repo", tmp_path / "restore", workspace=workspace,
    )
    assert report["failures"] == []
    assert report["local_snapshot"]["restored_files"] == 1
    assert report["local_snapshot"]["tag"] == release_tag
    assert (workspace / "runtime" / "restored-evidence.bin").read_bytes() == data
    assert report["status"] == "ASSETS_VERIFIED_ONLY"


def test_restore_missing_current_snapshot_index_fails_closed(tmp_path):
    import pytest

    module = _module()
    releases = tmp_path / "releases"
    current = releases / "alina-local-snapshot-new"
    current.mkdir(parents=True)
    with pytest.raises(module.RestoreError, match="missing current local snapshot index"):
        module.materialize_latest_local_snapshot(
            releases, tmp_path, allowed_release_dirs={current.name},
        )


def test_restore_corrupt_current_snapshot_does_not_use_older_snapshot(tmp_path):
    import pytest

    module = _module()
    releases = tmp_path / "releases"
    older = releases / "alina-local-snapshot-older"
    newer = releases / "alina-local-snapshot-newer"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps({
            "schema": "alina.local_snapshot.v1", "tag": older.name,
            "created_at_utc": "2026-10-10",
            "chunks": [], "files": [],
        }), encoding="utf-8",
    )
    (newer / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        "{invalid json", encoding="utf-8",
    )
    with pytest.raises(module.RestoreError, match="invalid current local snapshot index"):
        module.materialize_latest_local_snapshot(
            releases, tmp_path, allowed_release_dirs={older.name, newer.name},
        )


def test_restore_rejects_unrecognized_current_snapshot_schema(tmp_path):
    import pytest

    module = _module()
    releases = tmp_path / "releases"
    current = releases / "alina-local-snapshot-current"
    current.mkdir(parents=True)
    (current / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps({"schema": "unknown", "chunks": [], "files": []}),
        encoding="utf-8",
    )
    with pytest.raises(module.RestoreError, match="invalid current local snapshot schema"):
        module.materialize_latest_local_snapshot(
            releases, tmp_path, allowed_release_dirs={current.name},
        )


def test_recover_verifiable_salvages_only_hashed_assets(tmp_path, monkeypatch):
    module = _module()
    payload = b"exact-source-bytes"
    valid = {**_asset("valid.bin", "https://example.invalid/valid", payload),
             "id": 101, "state": "uploaded"}
    incomplete = {"id": 102, "name": "invalid.bin", "size": 400,
                  "digest": None, "state": "starter",
                  "browser_download_url": "https://example.invalid/invalid"}
    releases = [{"id": 7, "tag_name": "data-v2-mixed", "assets": [valid, incomplete]}]
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter(releases))
    calls = []
    def fake_download(url, target, **_k):
        calls.append(url)
        assert url.endswith("/valid")
        target.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(module, "_download_to_path", fake_download)
    root = tmp_path / "restore"
    result = module.restore_everything("owner/repo", root, recover_verifiable=True)
    assert calls == ["https://example.invalid/valid"]
    assert (root / "releases" / "data-v2-mixed" / "valid.bin").read_bytes() == payload
    assert result["status"] == "RESTORE_INCOMPLETE"
    assert result["unverified_source_asset_count"] == 1
    assert result["downloaded"] == 1
    assert result["source_asset_bytes"] == len(payload) + 400
    assert result["unverified_source_bytes"] == 400
    assert result["verified_asset_bytes"] == len(payload)
    assert result["missing_asset_bytes"] == 400
    assert result["source_byte_parity"] is False
    assert result["all_source_assets_accounted_for"] is False
    assert result["failures"][0]["error"] == "UNVERIFIABLE_SOURCE_ASSET"
    assert not (root / "releases" / "data-v2-mixed" / "invalid.bin").exists()
    report = json.loads((root / "RESTORE_REPORT.json").read_text())
    assert report["unverified_source_assets_sample"][0]["asset_id"] == 102


def test_recover_verifiable_never_promotes_stale_manifest(tmp_path, monkeypatch):
    module = _module()
    payload = b"uncertified"
    root = tmp_path / "restore"
    release = root / "releases" / "data-v2-starter"
    release.mkdir(parents=True)
    (release / "safe.bin").write_bytes(payload)
    (release / "RUN_MANIFEST.json").write_text(json.dumps({
        "manifests": [{
            "dataset_id": "danger", "quality_status": "SAFE",
            "validation_allowed": True, "replay_compatible": True,
            "asset_verified": True, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "release": {"repository": "owner/repo",
                        "release_tag": release.name, "asset_name": "safe.bin"},
        }],
    }))
    valid = {**_asset("safe.bin", "https://example.invalid/safe", payload),
             "id": 1, "state": "uploaded"}
    invalid = {"id": 2, "name": "RUN_MANIFEST.json", "size": 999,
               "digest": None, "state": "starter",
               "browser_download_url": "https://example.invalid/missing"}
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([
        {"id": 7, "tag_name": "data-v2-starter", "assets": [valid, invalid]},
    ]))
    result = module.restore_everything("owner/repo", root, recover_verifiable=True)
    assert result["status"] == "RESTORE_INCOMPLETE"
    assert result["classification"]["usable_shards"] == 0
    assert not list((root / "usable").rglob("*.jsonl.gz"))


def test_recover_verifiable_reports_source_gaps_in_preflight(tmp_path, monkeypatch):
    module = _module()
    invalid = {"id": 2, "name": "RUN_MANIFEST.json", "size": 999,
               "digest": None, "state": "starter",
               "browser_download_url": "https://example.invalid/missing"}
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([
        {"id": 7, "tag_name": "data-v2-starter", "assets": [invalid]},
    ]))
    result = module.restore_everything(
        "owner/repo", tmp_path / "restore",
        preflight_only=True, recover_verifiable=True,
    )
    assert result["unverified_source_asset_count"] == 1
    assert result["pending_download_bytes"] == 0
    assert result["source_asset_bytes"] == 999
    assert result["unverified_source_bytes"] == 999
    assert result["status"] == "PREFLIGHT_SOURCE_UNVERIFIABLE"


def test_salvage_refuses_unknown_release_state_even_with_a_sha256():
    module = _module()
    candidate = {
        "name": "missing-state.bin", "size": 3,
        "digest": "sha256:" + hashlib.sha256(b"abc").hexdigest(),
    }
    assert module._source_asset_eligible(candidate, salvage=False)
    assert not module._source_asset_eligible(candidate, salvage=True)
    candidate["state"] = "starter"
    assert not module._source_asset_eligible(candidate, salvage=True)
    candidate["state"] = "uploaded"
    assert module._source_asset_eligible(candidate, salvage=True)


def test_local_snapshot_cannot_overwrite_tracked_git_file(tmp_path):
    module = _module()
    clone = tmp_path / "fresh clone"
    clone.mkdir()
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    tracked = clone / "README.md"
    tracked.write_bytes(b"canonical-git-file")
    subprocess.run(["git", "-C", str(clone), "add", "README.md"], check=True)
    releases = tmp_path / "releases"
    directory = releases / "alina-local-snapshot-proven"
    directory.mkdir(parents=True)
    payload = b"malicious-snapshot-overwrite"
    name = "ALINA_LOCAL_SNAPSHOT.chunk0000.bin"
    (directory / name).write_bytes(payload)
    (directory / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text(
        json.dumps({
            "schema": "alina.local_snapshot.v1",
            "tag": directory.name,
            "chunks": [{
                "name": name, "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }],
            "files": [{
                "path": "README.md", "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "segments": [{"chunk": name, "offset": 0, "bytes": len(payload)}],
            }],
        }), encoding="utf-8",
    )
    with pytest.raises(module.RestoreError, match="overwrite tracked Git file"):
        module.materialize_latest_local_snapshot(
            releases, clone, allowed_release_dirs={directory.name},
        )
    assert tracked.read_bytes() == b"canonical-git-file"


def test_local_snapshot_rejects_nested_git_directories(tmp_path):
    import pytest

    module = _module()
    for relative in (".GIT/config", "runtime/.GiT/config", "runtime\\.git\\config"):
        with pytest.raises(module.RestoreError, match="inside .git|unsafe snapshot path"):
            module._safe_workspace_target(tmp_path, relative)


def test_optional_published_snapshot_succeeds_without_any_snapshot(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([]))
    report = module.restore_everything(
        "owner/repo", tmp_path, workspace=tmp_path,
        optional_local_snapshot=True,
    )
    assert report["local_snapshot"] == {
        "status": "NOT_PUBLISHED", "restored_files": 0,
    }
    assert report["failures"] == []
    assert report["source_byte_parity"] is True
    assert report["status"] == "ASSETS_VERIFIED_ONLY"
    assert json.loads((tmp_path / "RESTORE_REPORT.json").read_text())[
        "local_snapshot"
    ]["status"] == "NOT_PUBLISHED"


def test_optional_published_snapshot_refuses_corrupt_index(tmp_path, monkeypatch):
    module = _module()
    release = {
        "id": 55,
        "tag_name": "alina-local-snapshot-corrupt",
        "assets": [],
    }
    monkeypatch.setattr(
        module, "iter_releases", lambda *_a, **_kw: iter([release]),
    )
    directory = tmp_path / "releases" / release["tag_name"]
    directory.mkdir(parents=True)
    (directory / "ALINA_LOCAL_SNAPSHOT_INDEX.json").write_text("{broken")
    report = module.restore_everything(
        "owner/repo", tmp_path, workspace=tmp_path,
        optional_local_snapshot=True,
    )
    assert report["status"] == "RESTORE_INCOMPLETE"
    assert report["local_snapshot"]["status"] == "FAIL"
    assert report["failures"][0]["stage"] == "local_snapshot"


def test_snapshot_cli_options_are_mutually_exclusive(tmp_path):
    import pytest
    module = _module()
    with pytest.raises(SystemExit) as ex:
        module.main([
            "--everything", "--destination", str(tmp_path),
            "--materialize-local-snapshot",
            "--materialize-available-local-snapshot",
        ])
    assert ex.value.code == 2


def test_replay_ready_recovers_historical_safe_asset_missing_from_inventory(tmp_path, monkeypatch):
    module = _module()
    payload = b'{"trade_id":"historical"}\n'
    digest = hashlib.sha256(payload).hexdigest()
    tag = "archive-v2-historical-safe"
    name = "historical.jsonl.gz"
    asset = {
        **_asset(name, "https://example.invalid/historical", payload),
        "id": 991, "state": "uploaded",
    }
    # The main Release inventory is incomplete, but the authoritative tag
    # lookup and paginated assets endpoint still expose the published bytes.
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([]))
    calls = []
    def lookup(url, **_kw):
        calls.append(url)
        assert url.endswith("/releases/tags/" + tag)
        return {"id": 123, "tag_name": tag, "assets": []}
    monkeypatch.setattr(module, "_json", lookup)
    monkeypatch.setattr(module, "_list_release_assets",
                        lambda *_a, **_kw: [asset])
    def download(url, target, **_kw):
        assert url == asset["browser_download_url"]
        target.write_bytes(payload)
        return len(payload), digest
    monkeypatch.setattr(module, "_download_to_path", download)
    index = tmp_path / "DATA_INDEX.json"
    index.write_text(json.dumps({"shards": [{
        "dataset_id": "historical-safe", "quality_status": "SAFE",
        "replay_compatible": True, "validation_allowed": True,
        "asset_verified": True, "release_tag": tag,
        "release_asset": name, "bytes": len(payload), "sha256": digest,
    }]}), encoding="utf-8")
    metrics = tmp_path / "DATA_METRICS.json"
    metrics.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 1},
    }), encoding="utf-8")
    report = module.restore_everything(
        "owner/repo", tmp_path / "restored", catalog_path=index,
        metrics_path=metrics, profile="replay-ready",
    )
    assert calls
    assert report["status"] == "REPLAY_READY_COMPLETE"
    assert (tmp_path / "restored" / "usable" / "shards" /
            tag / "historical-safe.jsonl.gz").read_bytes() == payload


def test_replay_ready_profile_restores_only_catalog_safe_assets(tmp_path, monkeypatch):
    module = _module()
    safe_bytes = b'{"trade_id":"safe"}\n'
    rejected_bytes = b'{"trade_id":"rejected"}\n'
    safe_sha = hashlib.sha256(safe_bytes).hexdigest()
    rejected_sha = hashlib.sha256(rejected_bytes).hexdigest()
    releases = [{
        "tag_name": "data-v2-profile-test",
        "assets": [
            _asset("safe.jsonl.gz", "https://example.invalid/safe", safe_bytes),
            _asset("rejected.jsonl.gz", "https://example.invalid/rejected", rejected_bytes),
        ],
    }]
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter(releases))
    downloaded = []

    def fake_download(url, target, **_kw):
        downloaded.append(url)
        payload = safe_bytes if url.endswith("/safe") else rejected_bytes
        target.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", fake_download)
    index_path = tmp_path / "DATA_INDEX.json"
    index_path.write_text(json.dumps({"shards": [
        {
            "dataset_id": "safe-one", "quality_status": "SAFE",
            "replay_compatible": True, "validation_allowed": True,
            "asset_verified": True, "release_tag": "data-v2-profile-test",
            "release_asset": "safe.jsonl.gz", "bytes": len(safe_bytes),
            "sha256": safe_sha,
        },
        {
            "dataset_id": "bad-one", "quality_status": "REJECT",
            "replay_compatible": False, "release_tag": "data-v2-profile-test",
            "release_asset": "rejected.jsonl.gz", "bytes": len(rejected_bytes),
            "sha256": rejected_sha,
        },
    ]}), encoding="utf-8")
    metrics_path = tmp_path / "DATA_METRICS.json"
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 2},
    }), encoding="utf-8")
    cached_rejected = (tmp_path / "restored" / "releases" /
                       "data-v2-profile-test" / "rejected.jsonl.gz")
    cached_rejected.parent.mkdir(parents=True)
    cached_rejected.write_bytes(rejected_bytes)

    report = module.restore_everything(
        "owner/repo", tmp_path / "restored", catalog_path=index_path,
        metrics_path=metrics_path, profile="replay-ready", prune_unselected=True,
    )

    assert downloaded == ["https://example.invalid/safe"]
    assert report["status"] == "REPLAY_READY_COMPLETE"
    assert report["profile"] == "replay-ready"
    assert report["asset_count"] == 1
    assert report["full_archive_asset_count"] == 2
    assert report["excluded_full_archive_bytes"] == len(rejected_bytes)
    assert report["classification"]["usable_shards"] == 1
    assert report["classification"]["quarantined_shards"] == 0
    assert report["pruned_unselected_assets"] == 1
    assert report["pruned_unselected_bytes"] == len(rejected_bytes)
    assert not cached_rejected.exists()
    restored = (tmp_path / "restored" / "usable" / "shards" /
                "data-v2-profile-test" / "safe-one.jsonl.gz")
    assert restored.read_bytes() == safe_bytes
    assert not (tmp_path / "restored" / "releases" /
                "data-v2-profile-test" / "safe.jsonl.gz").exists()

    # A completed staged asset is proved by its outer identity plus every
    # materialized member, so an incremental run must not download it again.
    repeated = module.restore_everything(
        "owner/repo", tmp_path / "restored", catalog_path=index_path,
        metrics_path=metrics_path, profile="replay-ready", prune_unselected=True,
    )
    assert downloaded == ["https://example.invalid/safe"]
    assert repeated["status"] == "REPLAY_READY_COMPLETE"
    assert repeated["releases"][0]["assets"][0]["status"] == "MATERIALIZED_VERIFIED"


def test_replay_ready_staging_cleanup_is_idempotent_after_sha_receipt(
    tmp_path, monkeypatch,
):
    module = _module()
    payload = b'{"trade_id":"safe"}\n'
    digest = hashlib.sha256(payload).hexdigest()
    tag = "data-v2-idempotent-staging"
    name = "safe.jsonl.gz"
    asset = _asset(name, "https://example.invalid/safe", payload)
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([{
        "tag_name": tag, "assets": [asset],
    }]))

    def fake_download(_url, target, **_kw):
        target.write_bytes(payload)
        return len(payload), digest

    monkeypatch.setattr(module, "_download_to_path", fake_download)
    index_path = tmp_path / "DATA_INDEX.json"
    index_path.write_text(json.dumps({"shards": [{
        "dataset_id": "safe-one", "quality_status": "SAFE",
        "replay_compatible": True, "validation_allowed": True,
        "asset_verified": True, "release_tag": tag,
        "release_asset": name, "bytes": len(payload), "sha256": digest,
    }]}), encoding="utf-8")
    metrics_path = tmp_path / "DATA_METRICS.json"
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 1},
    }), encoding="utf-8")

    original_seal = module._write_staged_asset_receipt

    def seal_after_external_cleanup(destination, repository, release_tag, item, rows):
        receipt = original_seal(destination, repository, release_tag, item, rows)
        staged = (destination / ".staging" / "releases" /
                  module._safe_component(release_tag) / module._safe_component(name))
        module._windows_io_path(staged).unlink()
        return receipt

    monkeypatch.setattr(module, "_write_staged_asset_receipt", seal_after_external_cleanup)
    destination = tmp_path / "restored"
    report = module.restore_everything(
        "owner/repo", destination, catalog_path=index_path,
        metrics_path=metrics_path, profile="replay-ready",
    )
    assert report["status"] == "REPLAY_READY_COMPLETE"
    assert (destination / "usable" / "shards" / tag /
            "safe-one.jsonl.gz").read_bytes() == payload


def test_staged_receipt_verification_uses_bounded_parallel_workers(
    tmp_path, monkeypatch,
):
    import threading
    import time

    module = _module()
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def slow_receipt_check(*_args, **_kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return True

    monkeypatch.setattr(module, "_staged_materialized_asset_ok", slow_receipt_check)
    releases = []
    rows_by_asset = {}
    for index in range(12):
        tag = f"data-v2-parallel-{index}"
        name = f"asset-{index}.jsonl.gz"
        releases.append({"tag_name": tag, "assets": [{"name": name}]})
        rows_by_asset[(tag, name)] = [{"dataset_id": f"safe-{index}"}]

    result = module._verify_staged_materialized_assets(
        tmp_path, "owner/repo", releases, rows_by_asset,
    )
    assert result == {key: True for key in rows_by_asset}
    assert 1 < maximum_active <= module.VERIFY_WORKERS



def test_replay_ready_mixed_zip_materializes_only_safe_and_never_non_safe(
    tmp_path, monkeypatch,
):
    """A physical ZIP shared with PARTIAL/REJECT cannot contaminate usable data."""
    module = _module()
    tag = "data-v2-mixed-physical"
    payloads = {
        "safe-one": gzip.compress(b'{"trade_id":"safe"}\n', mtime=0),
        "partial-one": gzip.compress(b'{"trade_id":"partial"}\n', mtime=0),
        "reject-one": gzip.compress(b'{"trade_id":"reject"}\n', mtime=0),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in payloads.items():
            archive.writestr(f"{name}.jsonl.gz", payload)
    packed = buffer.getvalue()
    outer_sha = hashlib.sha256(packed).hexdigest()

    rows = []
    for name, status in (
        ("safe-one", "SAFE"), ("partial-one", "PARTIAL"), ("reject-one", "REJECT"),
    ):
        payload = payloads[name]
        rows.append({
            "dataset_id": name,
            "quality_status": status,
            # Even a positive replay flag cannot override a non-SAFE label.
            "replay_compatible": True,
            "validation_allowed": status == "SAFE",
            "asset_verified": True,
            "release_tag": tag,
            "release_asset": f"{name}.jsonl.gz",
            "release_container_asset": "mixed.zip",
            "release_remote_size": len(packed),
            "release_remote_digest": "sha256:" + outer_sha,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    index_path = tmp_path / "DATA_INDEX.json"
    index_path.write_text(json.dumps({"shards": rows}), encoding="utf-8")
    metrics_path = tmp_path / "DATA_METRICS.json"
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": len(rows)},
    }), encoding="utf-8")

    url = "https://example.invalid/mixed"
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_k: iter([{
        "tag_name": tag, "assets": [_asset("mixed.zip", url, packed)],
    }]))
    fetched = []

    def fake_download(source_url, target, **_kw):
        fetched.append(source_url)
        target.write_bytes(packed)
        return len(packed), outer_sha

    monkeypatch.setattr(module, "_download_to_path", fake_download)
    restored_root = tmp_path / "restored"
    result = module.restore_everything(
        "owner/repo", restored_root, catalog_path=index_path,
        metrics_path=metrics_path, profile="replay-ready", prune_unselected=True,
    )
    assert result["status"] == "REPLAY_READY_COMPLETE"
    assert fetched == [url]  # The shared physical archive is needed for SAFE.
    usable = restored_root / "usable" / "shards" / tag
    assert sorted(p.name for p in usable.glob("*.jsonl.gz")) == [
        "safe-one.jsonl.gz",
    ]
    assert (usable / "safe-one.jsonl.gz").read_bytes() == payloads["safe-one"]
    assert result["classification"]["usable_shards"] == 1
    assert result["classification"]["expected_usable_shards"] == 1
    assert result["classification"]["expected_usable_bytes"] == len(payloads["safe-one"])
    assert result["classification"]["materialization_complete"] is True
    # Replay/backtest readers consume the canonical gzip shard directly.  A
    # successful restore must therefore leave an actually decompressible
    # stream, not merely a correctly named ZIP member.
    with gzip.open(usable / "safe-one.jsonl.gz", "rb") as stream:
        assert stream.read() == b'{"trade_id":"safe"}\n'
    # First-stage extraction already checked the ZIP member against its
    # SHA-bound manifest; the final pass correctly reuses the verified shard.
    assert result["releases"][0]["assets"][0]["status"] == "STAGED_MATERIALIZED_VERIFIED"
    assert result["classification"]["skipped_verified_shards"] == 1
    assert result["classification"]["verified_zip_members"] == 0
    assert result["classification"]["quarantined_shards"] == 0
    assert not list((restored_root / "usable").rglob("*partial-one*"))
    assert not list((restored_root / "usable").rglob("*reject-one*"))
    unrelated_safe = (
        restored_root / "usable" / "shards" / "preserved-market-family"
        / "market-safe.jsonl.gz"
    )
    unrelated_safe.parent.mkdir(parents=True)
    unrelated_safe.write_bytes(b"historical-safe-shard")

    # A previously cached mixed ZIP can still contain PARTIAL/REJECT bytes.
    # Preserve the raw archive; only individually verified SAFE members enter
    # the usable replay tree.
    cached_outer = restored_root / "releases" / tag / "mixed.zip"
    cached_outer.parent.mkdir(parents=True, exist_ok=True)
    cached_outer.write_bytes(packed)
    second = module.restore_everything(
        "owner/repo", restored_root, catalog_path=index_path,
        metrics_path=metrics_path, profile="replay-ready", prune_unselected=True,
    )
    assert second["status"] == "REPLAY_READY_COMPLETE"
    assert cached_outer.read_bytes() == packed
    assert second["selected_release_cache"]["policy"] == "PRESERVE_RAW_RELEASE_CACHE"
    assert second["selected_release_cache"]["removed_assets"] == 0
    assert second["selected_release_cache"]["removed_bytes"] == 0
    assert unrelated_safe.read_bytes() == b"historical-safe-shard"
    assert fetched == [url]
    assert sorted(p.name for p in usable.glob("*.jsonl.gz")) == [
        "safe-one.jsonl.gz",
    ]


def test_replay_ready_preflight_counts_zip_extraction_space(tmp_path, monkeypatch):
    module = _module()
    member = b"compressed-safe-shard"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("safe.jsonl.gz", member)
    outer = stream.getvalue()
    release = {"tag_name": "data-v2-packed", "assets": [
        _asset("packed.zip", "https://example.invalid/packed", outer),
    ]}
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([release]))
    index_path = tmp_path / "DATA_INDEX.json"
    index_path.write_text(json.dumps({"shards": [{
        "dataset_id": "safe-packed", "quality_status": "SAFE",
        "replay_compatible": True, "validation_allowed": True,
        "asset_verified": True, "release_tag": "data-v2-packed",
        "release_asset": "safe.jsonl.gz",
        "release_container_asset": "packed.zip",
        "release_remote_size": len(outer),
        "release_remote_digest": "sha256:" + hashlib.sha256(outer).hexdigest(),
        "bytes": len(member), "sha256": hashlib.sha256(member).hexdigest(),
    }]}), encoding="utf-8")
    metrics_path = tmp_path / "DATA_METRICS.json"
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 1},
    }), encoding="utf-8")

    report = module.restore_everything(
        "owner/repo", tmp_path / "restored", catalog_path=index_path,
        metrics_path=metrics_path, profile="replay-ready", preflight_only=True,
    )

    assert report["pending_download_bytes"] == len(outer)
    assert report["pending_materialization_bytes"] == len(member)
    assert report["required_free_destination_bytes"] == (
        len(outer) + len(member) + report["safety_margin_bytes"]
    )


def test_replay_ready_materialization_refuses_symlinked_usable_tree(tmp_path):
    module = _module()
    payload = b"safe"
    releases = tmp_path / "releases"
    source = releases / "data-v2-safe"
    source.mkdir(parents=True)
    (source / "safe.jsonl.gz").write_bytes(payload)
    destination = tmp_path / "restore"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _create_symlink_or_skip(
        destination / "usable", outside, target_is_directory=True
    )
    row = {
        "dataset_id": "safe-one", "release_tag": "data-v2-safe",
        "release_asset": "safe.jsonl.gz", "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    report = module._materialize_catalog_safe_shards(
        [row], releases, destination,
    )

    assert report["usable_shards"] == 0
    assert report["failures"][0]["error"] == "SYMLINKED_SHARD_DIRECTORY"
    assert not list(outside.rglob("*.jsonl.gz"))


def test_replay_ready_stale_cleanup_refuses_symlinked_shards(tmp_path):
    module = _module()
    destination = tmp_path / "restore"
    stale_dir = destination / "usable" / "shards" / "obsolete"
    stale_dir.mkdir(parents=True)
    outside = tmp_path / "unrelated-data.bin"
    outside.write_bytes(b"must not follow, hash, move or delete")
    linked = stale_dir / "old.jsonl.gz"
    _create_symlink_or_skip(linked, outside)

    report = module._materialize_catalog_safe_shards(
        [], tmp_path / "releases", destination,
    )
    assert report["usable_shards"] == 0
    assert any(item.get("error") == "SYMLINKED_STALE_SHARD_NOT_PRUNED"
               for item in report["failures"])
    assert linked.is_symlink()
    assert outside.read_bytes() == b"must not follow, hash, move or delete"
    assert not (destination / "quarantine" / "stale_usable").exists()


def test_replay_ready_stale_cleanup_refuses_symlinked_root(tmp_path):
    module = _module()
    destination = tmp_path / "restore"
    (destination / "usable").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "old-release").mkdir()
    (outside / "old-release" / "old.jsonl.gz").write_bytes(b"non-catalog")
    _create_symlink_or_skip(
        destination / "usable" / "shards", outside, target_is_directory=True
    )

    report = module._materialize_catalog_safe_shards(
        [], tmp_path / "releases", destination,
    )
    assert report["usable_shards"] == 0
    assert any(item.get("error") == "SYMLINKED_USABLE_SHARD_ROOT"
               for item in report["failures"])
    assert (outside / "old-release" / "old.jsonl.gz").read_bytes() == b"non-catalog"


def test_replay_ready_prune_preserves_unknown_corrupt_and_symlinked_files(tmp_path):
    module = _module()
    expected = b"published"
    release_dir = tmp_path / "releases" / "old-release"
    release_dir.mkdir(parents=True)
    corrupt = release_dir / "asset.bin"
    corrupt.write_bytes(b"not-the-published-bytes")
    unknown = release_dir / "my-local-note.txt"
    unknown.write_text("keep me", encoding="utf-8")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(expected)
    linked = release_dir / "linked.bin"
    _create_symlink_or_skip(linked, outside)
    releases = [{"tag_name": "old-release", "assets": [
        _asset("asset.bin", "https://example.invalid/asset", expected),
        _asset("linked.bin", "https://example.invalid/linked", expected),
    ]}]

    result = module._prune_verified_unselected_assets(
        releases, set(), tmp_path / "releases",
    )

    assert result["assets"] == 0
    assert corrupt.read_bytes() == b"not-the-published-bytes"
    assert unknown.read_text(encoding="utf-8") == "keep me"
    assert linked.is_symlink()
    assert outside.read_bytes() == expected


def test_prune_only_removes_verified_local_non_safe_cache_without_payload_download(
    tmp_path, monkeypatch,
):
    module = _module()
    safe_bytes = b'{"safe":true}\n'
    rejected_bytes = b'{"rejected":true}\n'
    tag = "data-v2-cache-prune"
    releases = [{"tag_name": tag, "assets": [
        _asset("safe.jsonl.gz", "https://example.invalid/safe", safe_bytes),
        _asset("bad.jsonl.gz", "https://example.invalid/reject", rejected_bytes),
    ]}]
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter(releases))
    monkeypatch.setattr(
        module, "_download_to_path",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("cache prune must never download market payloads")
        ),
    )
    index_path = tmp_path / "DATA_INDEX.json"
    index_path.write_text(json.dumps({"shards": [
        {"dataset_id": "safe-cache", "quality_status": "SAFE",
         "replay_compatible": True, "validation_allowed": True,
         "asset_verified": True, "release_tag": tag,
         "release_asset": "safe.jsonl.gz", "bytes": len(safe_bytes),
         "sha256": hashlib.sha256(safe_bytes).hexdigest()},
        {"dataset_id": "bad-cache", "quality_status": "REJECT",
         "replay_compatible": False, "release_tag": tag,
         "release_asset": "bad.jsonl.gz", "bytes": len(rejected_bytes),
         "sha256": hashlib.sha256(rejected_bytes).hexdigest()},
    ]}), encoding="utf-8")
    metrics_path = tmp_path / "DATA_METRICS.json"
    metrics_path.write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 2},
    }), encoding="utf-8")
    destination = tmp_path / "restore"
    local_assets = destination / "releases" / tag
    local_assets.mkdir(parents=True)
    safe = local_assets / "safe.jsonl.gz"
    bad = local_assets / "bad.jsonl.gz"
    unknown = local_assets / "my-unpublished-note.txt"
    safe.write_bytes(safe_bytes)
    bad.write_bytes(rejected_bytes)
    unknown.write_text("preserve locally owned file", encoding="utf-8")

    report = module.restore_everything(
        "owner/repo", destination, catalog_path=index_path,
        metrics_path=metrics_path, profile="replay-ready",
        prune_only=True, max_download_bytes=0,
    )
    assert report["status"] == "CACHE_PRUNED_NOT_RESTORED"
    assert report["pruned_unselected_assets"] == 1
    assert report["pruned_unselected_bytes"] == len(rejected_bytes)
    assert report["market_payloads_downloaded"] is False
    assert report["github_release_payloads_deleted"] is False
    assert report["replay_ready_complete"] is False
    assert safe.read_bytes() == safe_bytes
    assert not bad.exists()
    assert unknown.read_text(encoding="utf-8") == "preserve locally owned file"
    assert not (destination / "RESTORE_REPORT.json").exists()
    assert (destination / "CACHE_PRUNE_REPORT.json").exists()


def test_prune_never_follows_symlinked_release_directory(tmp_path):
    module = _module()
    payload = b"important original outside cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "asset.bin").write_bytes(payload)
    releases_root = tmp_path / "releases"
    releases_root.mkdir()
    _create_symlink_or_skip(
        releases_root / "old-release", outside, target_is_directory=True
    )
    release = {"tag_name": "old-release", "assets": [
        _asset("asset.bin", "https://example.invalid/asset", payload),
    ]}
    report = module._prune_verified_unselected_assets(
        [release], set(), releases_root,
    )
    assert report["assets"] == 0
    assert report["failures"][0]["error"] == "SYMLINKED_RELEASE_DIRECTORY_NOT_PRUNED"
    assert (outside / "asset.bin").read_bytes() == payload


def test_release_asset_download_passes_exact_sha_bound_network_limit(monkeypatch, tmp_path):
    module = _module()

    checked = []
    def fake_download(url, target, *, token=None, max_bytes=None, **kwargs):
        checked.append(max_bytes)
        data = b"exact" if max_bytes else b""
        target.write_bytes(data)
        return len(data), hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(module, "_download_to_path", fake_download)
    monkeypatch.setattr(module, "_verify_zip_archive", lambda path, name: None)
    for payload in (b"exact", b""):
        asset = {
            "name": f"asset-{len(payload)}.bin",
            "size": len(payload),
            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "browser_download_url": "https://example.invalid/asset",
        }
        receipt = module.download_asset(asset, tmp_path)
        assert receipt["verification_status"] == "VERIFIED"
        assert (tmp_path / asset["name"]).read_bytes() == payload
    assert checked == [5, 0]


def test_default_verification_workers_respect_half_cpu_budget():
    module = _module()
    logical_processors = os.cpu_count() or 1
    assert module.VERIFY_WORKERS >= 1
    if logical_processors >= 2:
        assert logical_processors >= module.VERIFY_WORKERS * 2


def _analysis_receipt(tmp_path, *, kind="backtest", campaign_id="analysis-e7-backtest-v2"):
    campaigns = tmp_path / "catalog" / "campaigns"
    receipts = tmp_path / "catalog" / "receipts"
    campaigns.mkdir(parents=True)
    receipts.mkdir(parents=True)
    campaign = campaigns / f"{campaign_id}.json"
    campaign.write_text(json.dumps({"campaign_id": campaign_id}), encoding="utf-8")
    manifest_sha = hashlib.sha256(campaign.read_bytes()).hexdigest()
    row = {
        "schema": "alina.publication_receipt.v2",
        "campaign_id": campaign_id,
        "unit_id": "0",
        "kind": kind,
        "status": "COMPLETE",
        "phase": "ANALYZE",
        "phase_epoch": 7,
        "source_collection_epoch": 6,
        "collection_cutoff_at_utc": "2026-10-04T12:21:46Z",
        "dataset_selection_id": "a" * 64,
        "code_sha": "b" * 40,
        "alina_head": "b" * 40,
        "manifest_sha256": manifest_sha,
        "checkpoint_id": "c" * 64,
        "payload_digest": "d" * 64,
        "result_sha256": "e" * 64,
        "evidence_tag": f"campaign-evidence-{campaign_id}-u0",
        "publication_state": "RELEASE_AND_RECEIPT_WRITTEN",
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    (receipts / f"{campaign_id}-u0.json").write_text(
        json.dumps(row), encoding="utf-8"
    )
    return row, receipts, campaigns


def test_certified_working_set_selects_provenance_bound_analysis_evidence(tmp_path):
    module = _module()
    receipt, receipts, campaigns = _analysis_receipt(tmp_path)
    evidence = b"paper evidence"
    asset = _asset("evidence.tgz", "https://example.invalid/evidence", evidence)
    releases = [{"tag_name": receipt["evidence_tag"], "assets": [asset]}]

    result = module.build_certified_working_set(
        releases,
        raw_required={("data-v2-safe", "safe.zip"): (12, "f" * 64)},
        receipts_root=receipts,
        campaigns_root=campaigns,
        repository="owner/repo",
    )

    assert result["status"] == "CERTIFIED_WORKING_SET_PLANNED"
    assert result["failures"] == []
    assert result["by_class"]["collections"]["asset_count"] == 1
    assert result["by_class"]["backtests"]["asset_count"] == 1
    assert result["required_assets"][(receipt["evidence_tag"], "evidence.tgz")] == (
        len(evidence), hashlib.sha256(evidence).hexdigest()
    )


def test_certified_working_set_excludes_unbound_analysis_receipt(tmp_path):
    module = _module()
    receipt, receipts, campaigns = _analysis_receipt(tmp_path)
    path = next(receipts.glob("*.json"))
    receipt["dataset_selection_id"] = "not-a-sha"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    result = module.build_certified_working_set(
        [], raw_required={}, receipts_root=receipts,
        campaigns_root=campaigns, repository="owner/repo",
    )

    assert result["status"] == "CERTIFIED_WORKING_SET_INCOMPLETE"
    assert result["excluded_receipts"] == 1
    assert result["failures"][0]["reason"] == "INVALID_ANALYSIS_PROVENANCE"


def test_certified_working_set_accepts_only_git_proven_crlf_checkout(tmp_path):
    module = _module()
    receipt, receipts, campaigns = _analysis_receipt(tmp_path)
    campaign = campaigns / f"{receipt['campaign_id']}.json"
    canonical = (
        b'{\n'
        b'  "campaign_id": "analysis-e7-backtest-v2",\n'
        b'  "paper_only": true\n'
        b'}\n'
    )
    campaign.write_bytes(canonical)
    receipt["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    next(receipts.glob("*.json")).write_text(json.dumps(receipt), encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "restore-test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Restore Test"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "core.autocrlf", "false"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "add", campaign.relative_to(tmp_path).as_posix()],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "canonical campaign"], cwd=tmp_path, check=True
    )

    campaign.write_bytes(canonical.replace(b"\n", b"\r\n"))
    evidence = b"paper evidence"
    release = {
        "tag_name": receipt["evidence_tag"],
        "assets": [_asset("evidence.tgz", "https://example.invalid/evidence", evidence)],
    }
    result = module.build_certified_working_set(
        [release],
        raw_required={},
        receipts_root=receipts,
        campaigns_root=campaigns,
        repository="owner/repo",
    )
    assert result["failures"] == []

    campaign.write_bytes(campaign.read_bytes().replace(b"true", b"false"))
    tampered = module.build_certified_working_set(
        [release],
        raw_required={},
        receipts_root=receipts,
        campaigns_root=campaigns,
        repository="owner/repo",
    )
    assert tampered["failures"][0]["reason"] == "INVALID_ANALYSIS_PROVENANCE"


def test_materialize_analysis_evidence_keeps_valid_negative_results(tmp_path):
    module = _module()
    receipt, _receipts, _campaigns = _analysis_receipt(tmp_path)
    result = {"status": "COMPLETE", "payload": {"net_usd": -5.25}}

    def canonical(value):
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()

    receipt["payload_digest"] = hashlib.sha256(canonical(result["payload"])).hexdigest()
    receipt["result_sha256"] = hashlib.sha256(canonical(result)).hexdigest()
    archive = tmp_path / "evidence.tgz"
    raw = json.dumps(result).encode()
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("result.json")
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))

    restored = module.materialize_analysis_evidence(
        archive, receipt, tmp_path / "usable"
    )

    assert restored["status"] == "VERIFIED"
    assert restored["economic_result"] == "VALID_NEGATIVE_RETAINED"
    assert restored["file_count"] == 1
    assert json.loads((Path(restored["destination"]) / "result.json").read_text())["payload"]["net_usd"] == -5.25
    repeated = module.materialize_analysis_evidence(
        archive, receipt, tmp_path / "usable"
    )
    assert repeated["status"] == "SKIPPED_VERIFIED"
    assert repeated["destination"] == restored["destination"]


def test_materialize_analysis_evidence_accepts_tar_root_and_legacy_preannotation(tmp_path):
    module = _module()
    receipt, _receipts, _campaigns = _analysis_receipt(tmp_path)
    result = {
        "status": "COMPLETE",
        "payload": {"net_usd": 1.25},
        "progressed": True,
    }

    def canonical(value):
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()

    result["sha256"] = hashlib.sha256(canonical(result["payload"])).hexdigest()
    annotated = json.loads(json.dumps(result))
    annotated["payload"].update({
        "evidence_release_tag": receipt["evidence_tag"],
        "evidence_repository": "owner/repo",
        "durable_persisted": True,
    })
    annotated["sha256"] = hashlib.sha256(canonical(annotated["payload"])).hexdigest()
    receipt["payload_digest"] = annotated["sha256"]
    receipt["result_sha256"] = hashlib.sha256(canonical(annotated)).hexdigest()
    receipt["_source_repository"] = "owner/repo"
    archive = tmp_path / "legacy-evidence.tgz"
    source = tmp_path / "source"
    source.mkdir()
    (source / "result.json").write_text(json.dumps(result), encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source, arcname=".")

    restored = module.materialize_analysis_evidence(
        archive, receipt, tmp_path / "usable"
    )

    assert restored["status"] == "VERIFIED"
    proof = json.loads(
        (Path(restored["destination"]) / "CERTIFIED_EVIDENCE.json").read_text()
    )
    assert proof["receipt_binding"] == "LEGACY_PREANNOTATION_RECONSTRUCTED"


def test_preflight_cli_refuses_missing_analysis_evidence_even_if_disk_is_sufficient(
    tmp_path, monkeypatch, capsys,
):
    module = _module()
    def fake_restore(*_args, **kwargs):
        assert kwargs["preflight_only"] is True
        return {
            "status": "PREFLIGHT_WORKING_SET_INCOMPLETE",
            "enough_disk_for_release_assets": True,
            "unverified_source_asset_count": 0,
            "full_archive_asset_bytes": 861_000,
            "source_asset_bytes": 120_000,
            "excluded_full_archive_bytes": 741_000,
        }
    monkeypatch.setattr(module, "restore_everything", fake_restore)
    result = module.main(["--replay-ready", "--preflight-only",
                          "--destination", str(tmp_path / "restore")])
    assert result == 3
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PREFLIGHT_WORKING_SET_INCOMPLETE"
    assert output["full_archive_asset_bytes"] == 861_000
    assert output["source_asset_bytes"] == 120_000
    assert output["excluded_full_archive_bytes"] == 741_000


def test_preflight_cli_ready_only_certifies_a_plan_not_a_restore(
    tmp_path, monkeypatch, capsys,
):
    module = _module()
    def fake_restore(*_args, **kwargs):
        assert kwargs["preflight_only"] is True
        return {
            "status": "PREFLIGHT_READY_NOT_RESTORED",
            "enough_disk_for_release_assets": True,
            "unverified_source_asset_count": 0,
            "full_archive_asset_count": 2,
            "full_archive_asset_bytes": 500,
            "excluded_full_archive_bytes": 400,
            "asset_count": 1,
            "source_asset_bytes": 100,
        }
    monkeypatch.setattr(module, "restore_everything", fake_restore)
    result = module.main(["--replay-ready", "--preflight-only",
                          "--destination", str(tmp_path / "restore")])
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PREFLIGHT_READY_NOT_RESTORED"
    assert output["full_archive_asset_count"] == 2
    assert output["full_archive_asset_bytes"] == 500
    assert output["asset_count"] == 1
    assert output["source_asset_bytes"] == 100
    assert output["excluded_full_archive_bytes"] == 400

def test_replay_restore_default_cli_preserves_historical_cache(monkeypatch, tmp_path):
    module = _module()
    seen = {}

    def capture(*_args, **kwargs):
        seen.update(kwargs)
        raise module.RestoreError("STOP_BEFORE_NETWORK")

    monkeypatch.setattr(module, "restore_everything", capture)
    assert module.main(["--replay-ready", "--destination", str(tmp_path)]) == 2
    assert seen["prune_unselected"] is False
    assert seen["max_download_bytes"] == 8 * (1024 ** 3)

    seen.clear()
    assert module.main([
        "--replay-ready", "--destination", str(tmp_path),
        "--retain-unselected-cache", "--max-download-gib", "3",
    ]) == 2
    assert seen["prune_unselected"] is False
    assert seen["max_download_bytes"] == 3 * (1024 ** 3)


def test_replay_restore_can_prune_verified_non_safe_cache_during_restore(
    monkeypatch, tmp_path,
):
    module = _module()
    seen = {}

    def capture(*_args, **kwargs):
        seen.update(kwargs)
        raise module.RestoreError("STOP_BEFORE_NETWORK")

    monkeypatch.setattr(module, "restore_everything", capture)
    assert module.main([
        "--replay-ready", "--prune-unselected-cache",
        "--destination", str(tmp_path),
    ]) == 2
    assert seen["prune_unselected"] is True
    assert seen["prune_only"] is False


def test_replay_download_budget_is_checked_before_pruning_or_any_payload(
    monkeypatch, tmp_path,
):
    module = _module()
    safe_bytes = b"valid-safe"
    rejected_bytes = b"old-rejected"
    safe_sha = hashlib.sha256(safe_bytes).hexdigest()
    release = {"tag_name": "data-v2-budget", "assets": [
        _asset("safe.jsonl.gz", "https://example.invalid/safe", safe_bytes),
        _asset("rejected.jsonl.gz", "https://example.invalid/reject", rejected_bytes),
    ]}
    monkeypatch.setattr(module, "iter_releases", lambda *_a, **_kw: iter([release]))
    catalog = tmp_path / "DATA_INDEX.json"
    catalog.write_text("{}", encoding="utf-8")
    metrics = tmp_path / "DATA_METRICS.json"
    metrics.write_text("{}", encoding="utf-8")
    row = {
        "dataset_id": "safe", "release_tag": "data-v2-budget",
        "release_asset": "safe.jsonl.gz", "bytes": len(safe_bytes),
        "sha256": safe_sha,
    }
    monkeypatch.setattr(module, "_load_replay_ready_plan", lambda *_a, **_kw: (
        {"source_index_sha256": "a" * 64, "safe_catalog_shards": 1},
        [row],
        {("data-v2-budget", "safe.jsonl.gz"): (len(safe_bytes), safe_sha)},
    ))
    downloads = []
    monkeypatch.setattr(
        module, "_download_to_path",
        lambda *_a, **_kw: downloads.append("FORBIDDEN"),
    )
    dest = tmp_path / "recovery"
    old = dest / "releases" / "data-v2-budget" / "rejected.jsonl.gz"
    old.parent.mkdir(parents=True)
    old.write_bytes(rejected_bytes)

    plan = module.restore_everything(
        "owner/repo", dest, catalog_path=catalog, metrics_path=metrics,
        profile="replay-ready", max_download_bytes=5,
        prune_unselected=True, preflight_only=True,
    )
    assert plan["status"] == "PREFLIGHT_DOWNLOAD_BUDGET_EXCEEDED"
    assert plan["pending_download_bytes"] == len(safe_bytes)
    assert plan["download_budget_ok"] is False

    import pytest
    with pytest.raises(module.RestoreError, match="download budget exceeded"):
        module.restore_everything(
            "owner/repo", dest, catalog_path=catalog, metrics_path=metrics,
            profile="replay-ready", max_download_bytes=5, prune_unselected=True,
        )
    assert downloads == []
    assert old.read_bytes() == rejected_bytes


def test_unlimited_download_requires_replay_profile_and_disallows_preview(capsys):
    module = _module()
    assert module.main(["--everything", "--unlimited-download"]) == 2
    assert "requires --replay-ready" in capsys.readouterr().err
    assert module.main(["--replay-ready", "--unlimited-download", "--preflight-only"]) == 2
    assert "incompatible with prune/preflight" in capsys.readouterr().err


def test_unlimited_download_passes_none_budget_to_existing_engine(
    monkeypatch, tmp_path,
):
    module = _module()
    seen = {}

    def fake_restore(*args, **kwargs):
        seen.update(kwargs)
        raise module.RestoreError("STOP_BEFORE_NETWORK")

    monkeypatch.setattr(module, "restore_everything", fake_restore)
    assert module.main([
        "--replay-ready", "--unlimited-download",
        "--destination", str(tmp_path),
    ]) == 2
    assert seen["profile"] == "replay-ready"
    assert seen["max_download_bytes"] is None


def test_unlimited_download_rejects_explicit_cap_before_network(capsys):
    module = _module()
    for parameters in (
        ["--max-download-gib", "32"],
        ["--max-download-gib=32"],
    ):
        assert module.main(["--replay-ready", "--unlimited-download", *parameters]) == 2
        assert "--unlimited-download conflicts with --max-download-gib" in capsys.readouterr().err


def test_fast_safe_inventory_downloads_snapshot_after_one_page(monkeypatch):
    module = _module()
    expected = {
        "id": 101, "tag_name": "historical-safe",
        "assets": [{**_asset("old.jsonl.gz", "https://example.invalid/old", b"payload"),
                    "id": 201, "state": "uploaded"}],
    }
    inventory = {
        "id": 999, "tag_name": "alina-restore-inventory-102-1",
        "assets": [{
            **_asset("RESTORE_INVENTORY.json.gz", "https://example.invalid/inv", b"inv"),
            "id": 1001, "state": "uploaded",
        }],
    }
    new = {
        "id": 1000, "tag_name": "current-safe",
        "assets": [{**_asset("new.jsonl.gz", "https://example.invalid/new", b"new"),
                    "id": 2002, "state": "uploaded"}],
    }
    calls = []
    def request(url, **_kwargs):
        calls.append(url)
        if "page=1" in url:
            return [new, inventory]
        raise AssertionError(f"unexpected deep scan: {url}")
    monkeypatch.setattr(module, "_json", request)
    monkeypatch.setattr(
        module, "_read_restore_inventory_asset",
        lambda *_a, **_k: [expected],
    )
    rows = list(module.iter_releases("owner/repo", prefer_published_inventory=True))
    assert {row["tag_name"] for row in rows} == {"historical-safe", "current-safe"}
    assert calls == ["https://api.github.com/repos/owner/repo/releases?per_page=100&page=1"]


def test_fast_safe_inventory_missing_snapshot_fails_not_silent_deep_scan(monkeypatch):
    import pytest
    module = _module()
    requests = []
    def request(url, **_kwargs):
        requests.append(url)
        return [{"id": 1, "tag_name": "data-v2-new", "assets": []}]
    monkeypatch.setattr(module, "_json", request)
    with pytest.raises(module.RestoreError, match="SAFE_INVENTORY_UNAVAILABLE"):
        list(module.iter_releases("owner/repo", prefer_published_inventory=True))
    assert len(requests) == 1


def test_fast_safe_inventory_changed_asset_sha_fails_closed(monkeypatch):
    import pytest
    module = _module()
    live_asset = {**_asset("safe.gz", "https://example.invalid/live", b"new"),
                  "id": 5, "state": "uploaded"}
    historical_asset = {**_asset("safe.gz", "https://example.invalid/historical", b"old"),
                        "id": 5, "state": "uploaded"}
    inventory = {
        "id": 999, "tag_name": "alina-restore-inventory-888-1",
        "assets": [{
            **_asset("RESTORE_INVENTORY.json.gz", "https://example.invalid/inventory", b"inventory"),
            "id": 900, "state": "uploaded",
        }],
    }
    monkeypatch.setattr(
        module, "_json",
        lambda *_a, **_k: [
            {"id": 11, "tag_name": "current-safe", "assets": [live_asset]},
            inventory,
        ],
    )
    monkeypatch.setattr(
        module, "_read_restore_inventory_asset",
        lambda *_a, **_k: [{
            "id": 11, "tag_name": "current-safe", "assets": [historical_asset],
        }],
    )
    with pytest.raises(module.RestoreError, match="asset identity conflicts"):
        list(module.iter_releases("owner/repo", prefer_published_inventory=True))

