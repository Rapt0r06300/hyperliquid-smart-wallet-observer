from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
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
    assert report["failures"] == []
    assert report["verification_failures"] == 0
    assert report["run_manifest_checks"][0]["status"] == "OK"
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



def test_iter_releases_enumerates_asset_pages_not_truncated_embedded_list(monkeypatch):
    module = _module()
    def a(index):
        return {
            **_asset(f"part-{index:03}.bin", f"https://example.invalid/{index}", bytes([index % 256])),
            "id": index + 1,
            "state": "uploaded",
        }
    releases = [{"id": 123, "tag_name": "data-v2-many", "assets": [a(i) for i in range(30)]}]
    calls = []
    def fake_json(url, **_kwargs):
        calls.append(url)
        if "/releases?" in url:
            return releases
        if "123/assets?" in url and url.endswith("&page=1"):
            return [a(i) for i in range(100)]
        if "123/assets?" in url and url.endswith("&page=2"):
            return [a(i) for i in range(100, 105)]
        raise AssertionError(url)
    monkeypatch.setattr(module, "_json", fake_json)
    rows = list(module.iter_releases("owner/repo"))
    assert len(rows) == 1
    assert len(rows[0]["assets"]) == 105
    assert rows[0]["assets"][-1]["name"] == "part-104.bin"
    assert len([url for url in calls if "/assets?" in url]) == 2


def test_iter_releases_rejects_malformed_or_duplicate_asset_pages(monkeypatch):
    module = _module()
    asset = {**_asset("one.bin", "https://example.invalid/one", b"a"), "id": 7, "state": "uploaded"}
    def fake_json(url, **_kwargs):
        if "/releases?" in url:
            return [{"id": 1, "tag_name": "one", "assets": []}]
        if url.endswith("&page=1"):
            return [asset] * 100
        return []
    monkeypatch.setattr(module, "_json", fake_json)
    import pytest
    with pytest.raises(module.RestoreError, match="duplicated asset id"):
        list(module.iter_releases("owner/repo"))


def test_iter_releases_rejects_asset_without_provable_hash(monkeypatch):
    module = _module()
    def fake_json(url, **_kwargs):
        if "/releases?" in url:
            return [{"id": 1, "tag_name": "one", "assets": []}]
        return [{**_asset("one.bin", "https://example.invalid/one", b"a"),
                 "id": 7, "state": "uploaded", "digest": None}]
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
    import pytest

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


def test_release_pagination_uses_small_pages_and_enumerates_every_release(monkeypatch):
    module = _module()
    urls = []
    def fetch_json(url, **_kwargs):
        urls.append(url)
        if "releases?" not in url:
            raise AssertionError(url)
        page = int(url.rsplit("page=", 1)[1])
        return [
            {"id": n + 1, "tag_name": f"release-{n + 1}", "assets": []}
            for n in range((page - 1) * 10, min(page * 10, 23))
        ]
    monkeypatch.setattr(module, "_json", fetch_json)
    monkeypatch.setattr(module, "_list_release_assets", lambda *_a, **_k: [])
    result = list(module.iter_releases("owner/repo"))
    assert len(result) == 23
    assert len({x["id"] for x in result}) == 23
    assert len(urls) == 3
    assert all("per_page=10" in url for url in urls)


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
