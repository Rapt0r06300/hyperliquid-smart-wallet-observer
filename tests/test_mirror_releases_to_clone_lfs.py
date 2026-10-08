from __future__ import annotations

import hashlib
import importlib.util
import json
import urllib.request
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


def test_public_fallback_strips_authorization_but_keeps_api_headers():
    module = _module()
    request = urllib.request.Request(
        "https://api.github.com/repos/o/r/releases",
        headers={
            "Authorization": "Bearer secret",
            "Accept": "application/vnd.github+json",
            "User-Agent": "test-agent",
        },
    )

    anonymous = module._without_authorization(request)
    headers = {key.lower(): value for key, value in anonymous.header_items()}

    assert "authorization" not in headers
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["user-agent"] == "test-agent"


def test_release_pagination_fails_closed_without_link(monkeypatch):
    module = _module()

    def full_page(_repository, *, page, per_page, token):
        assert page == 1
        return [{"id": n, "assets": []} for n in range(per_page)], {}

    monkeypatch.setattr(module, "_api_page", full_page)

    try:
        list(module.iter_releases_oldest_first("owner/repo"))
    except module.MirrorError as exc:
        assert "pagination" in str(exc)
    else:
        raise AssertionError("A truncated Release inventory must never be complete")


def test_release_pagination_reads_every_page_oldest_first(monkeypatch):
    module = _module()
    observed = []

    def pages(_repository, *, page, per_page, token):
        assert per_page == 5
        observed.append(page)
        rows = {
            1: [{"id": n, "assets": []} for n in range(15, 10, -1)],
            2: [{"id": n, "assets": []} for n in range(10, 5, -1)],
            3: [{"id": n, "assets": []} for n in range(5, 0, -1)],
        }
        headers = {
            "Link": '<https://api.github.com/repos/o/r/releases?per_page=5&page=3>; rel="last"'
        }
        return rows[page], headers

    monkeypatch.setattr(module, "_api_page", pages)
    items = list(module.iter_releases_oldest_first("owner/repo"))

    assert [row["id"] for row in items] == list(range(1, 16))
    assert observed == [1, 3, 2]


def test_release_pagination_rejects_expensive_page_size():
    module = _module()
    try:
        list(module.iter_releases_oldest_first("owner/repo", per_page=100))
    except module.MirrorError as exc:
        assert "between 1 and 10" in str(exc)
    else:
        raise AssertionError("Unbounded Release pagination must be rejected")



def test_select_pending_rejects_single_asset_over_batch_bytes():
    module = _module()
    release = {
        "id": 1, "tag_name": "v1",
        "assets": [{"id": 100, "name": "huge.bin", "size": 1_500_000_001}],
    }
    try:
        module.select_pending_assets([release], set(), max_assets=10, max_bytes=1_500_000_000)
    except module.MirrorError as exc:
        assert "larger than" in str(exc)
    else:
        raise AssertionError("must not silently exceed runner byte cap")


def test_select_pending_refuses_incomplete_release_inventory():
    module = _module()
    try:
        module.select_pending_assets([{"id": 1}], set(), max_assets=10, max_bytes=100)
    except module.MirrorError as exc:
        assert "inventory" in str(exc)
    else:
        raise AssertionError("missing inventory must fail closed")


def test_select_pending_respects_total_byte_limit():
    module = _module()
    release = {
        "id": 1, "tag_name": "v1",
        "assets": [
            {"id": 1, "name": "one.bin", "size": 60},
            {"id": 2, "name": "two.bin", "size": 50},
        ],
    }
    rows = module.select_pending_assets([release], set(), max_assets=10, max_bytes=100)
    assert [asset["id"] for _rel, asset in rows] == [1]
