from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "mirror_releases_to_clone_lfs_test",
        ROOT / "tools" / "mirror_releases_to_clone_lfs.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_last_page_from_link():
    module = _module()
    link = (
        '<https://api.github.com/repos/o/r/releases?per_page=10&page=2>; rel="next", '
        '<https://api.github.com/repos/o/r/releases?per_page=10&page=17>; rel="last"'
    )
    assert module._last_page_from_link(link) == 17


def test_select_pending_assets_is_bounded_and_skips_known():
    module = _module()
    releases = [
        {
            "id": 1,
            "tag_name": "old",
            "assets": [
                {"id": 10, "name": "a.bin", "size": 50},
                {"id": 11, "name": "b.bin", "size": 60},
            ],
        },
        {
            "id": 2,
            "tag_name": "new",
            "assets": [
                {"id": 12, "name": "c.bin", "size": 70},
            ],
        },
    ]

    selected = module.select_pending_assets(
        releases,
        {10},
        max_assets=10,
        max_bytes=100,
    )

    assert [asset["id"] for _release, asset in selected] == [11]


def test_asset_target_uses_asset_id_and_refuses_secret_like_names():
    module = _module()
    release = {"id": 1, "tag_name": "data-v2/test"}
    asset = {"id": 123, "name": "trades.jsonl.gz", "size": 10}

    target = module.asset_target(asset, release)

    assert target.parts[0] == "clone_payload"
    assert target.parts[1] == "releases"
    assert target.name.startswith("123--")
    assert "/" not in target.name

    bad = {"id": 124, "name": "private-key.bin", "size": 10}
    try:
        module.asset_target(bad, release)
    except module.MirrorError as exc:
        assert "secret-like" in str(exc)
    else:
        raise AssertionError("secret-like Release assets must fail closed")


def test_mirror_batch_records_exact_size_sha_and_clone_path(tmp_path, monkeypatch):
    module = _module()
    manifest_path = tmp_path / module.MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "alina.clone_payload_manifest.v1",
                "repository": "owner/repo",
                "entries": [],
                "total_assets": 0,
                "total_bytes": 0,
                "source": "github_releases",
                "read_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )

    payload = b"exact-release-bytes"
    sha = hashlib.sha256(payload).hexdigest()
    release = {
        "id": 77,
        "tag_name": "data-v2-test",
        "name": "test release",
        "assets": [
            {
                "id": 9001,
                "name": "trades.jsonl.gz",
                "size": len(payload),
                "digest": "sha256:" + sha,
                "browser_download_url": "https://example.invalid/trades",
            }
        ],
    }
    monkeypatch.setattr(
        module,
        "iter_releases_oldest_first",
        lambda *_args, **_kwargs: iter([release]),
    )

    def fake_download(asset, target, **_kwargs):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return len(payload), sha

    monkeypatch.setattr(module, "_stream_download", fake_download)

    report = module.mirror_batch(
        "owner/repo",
        root=tmp_path,
        max_assets=500,
        max_bytes=700 * 1024 * 1024,
        token=None,
    )

    assert report["added_assets"] == 1
    assert report["added_bytes"] == len(payload)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    row = manifest["entries"][0]
    assert row["asset_id"] == 9001
    assert row["bytes"] == len(payload)
    assert row["sha256"] == sha
    mirrored = tmp_path / row["clone_path"]
    assert mirrored.read_bytes() == payload


def test_known_asset_ids_is_idempotency_authority():
    module = _module()
    manifest = {
        "schema": "alina.clone_payload_manifest.v1",
        "entries": [
            {"asset_id": 1},
            {"asset_id": 2},
            {"asset_id": 0},
            {"asset_id": None},
        ],
    }
    assert module.known_asset_ids(manifest) == {1, 2}
