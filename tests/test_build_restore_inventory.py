import importlib.util
import gzip
import hashlib
import json
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / "tools" / "build_restore_inventory.py"
    spec = importlib.util.spec_from_file_location("build_restore_inventory_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_inventory_is_complete_minimal_and_excludes_prior_inventory_releases():
    module = _module()
    asset = {
        "id": 11,
        "name": "part.bin",
        "size": 3,
        "digest": "sha256:" + "a" * 64,
        "state": "uploaded",
        "browser_download_url": "https://github.com/o/r/releases/download/data-1/part.bin",
        "content_type": "application/octet-stream",
    }
    releases = {
        "data-1": {"id": 1, "tag_name": "data-1", "assets": [asset]},
        "alina-restore-inventory-old": {
            "id": 2,
            "tag_name": "alina-restore-inventory-old",
            "assets": [],
        },
    }

    payload = module.build_inventory(
        "o/r", list(releases), lambda tag: releases[tag], generated_at="now"
    )

    assert payload["schema"] == "alina.restore_inventory.v1"
    assert payload["repository"] == "o/r"
    assert payload["generated_at_utc"] == "now"
    assert payload["release_count"] == 1
    assert payload["asset_count"] == 1
    assert payload["source_asset_bytes"] == 3
    assert payload["releases"] == [{
        "id": 1,
        "tag_name": "data-1",
        "assets": [{
            "id": 11,
            "name": "part.bin",
            "size": 3,
            "digest": "sha256:" + "a" * 64,
            "state": "uploaded",
            "browser_download_url": (
                "https://github.com/o/r/releases/download/data-1/part.bin"
            ),
        }],
    }]


def test_fetch_all_releases_retries_transient_tag_lookup_404(monkeypatch):
    module = _module()
    calls = []

    def flaky_json(url, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise module.RestoreError("HTTP 404 for release tag")
        return {"id": 7, "tag_name": "data-one", "assets": []}

    monkeypatch.setattr(module, "_json", flaky_json)
    found = module._fetch_all_releases("o/r", ["data-one"], "token", 1)
    assert found["data-one"]["id"] == 7
    assert len(calls) == 2


def test_fetch_all_releases_never_silently_drops_persistent_404(monkeypatch):
    module = _module()
    monkeypatch.setattr(
        module,
        "_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            module.RestoreError("HTTP 404 for release tag")
        ),
    )
    with pytest.raises(module.RestoreError, match="HTTP 404"):
        module._fetch_all_releases("o/r", ["data-one"], "token", 1)


def test_load_base_inventory_verifies_asset_and_reuses_historical_releases(monkeypatch):
    module = _module()
    inventory = {
        "schema": "alina.restore_inventory.v1",
        "repository": "o/r",
        "releases": [{"id": 7, "tag_name": "data-one", "assets": []}],
    }
    raw = gzip.compress(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode(),
        mtime=0,
    )
    digest = hashlib.sha256(raw).hexdigest()
    release = {
        "id": 9,
        "tag_name": "alina-restore-inventory-123-1",
        "assets": [{
            "id": 10,
            "name": "RESTORE_INVENTORY.json.gz",
            "size": len(raw),
            "digest": f"sha256:{digest}",
            "state": "uploaded",
            "browser_download_url": "https://example.invalid/inventory.gz",
        }],
    }
    calls = []

    def fake_json(url, **_kwargs):
        calls.append(url)
        return release

    monkeypatch.setattr(module, "_json", fake_json)
    monkeypatch.setattr(module, "_request", lambda *_args, **_kwargs: raw)

    found = module._load_base_inventory(
        "o/r", ["data-one", release["tag_name"]], "token"
    )

    assert found == {"data-one": inventory["releases"][0]}
    assert len(calls) == 1


def test_load_base_inventory_rejects_corrupt_published_bytes(monkeypatch):
    module = _module()
    release = {
        "id": 9,
        "tag_name": "alina-restore-inventory-123-1",
        "assets": [{
            "id": 10,
            "name": "RESTORE_INVENTORY.json.gz",
            "size": 3,
            "digest": "sha256:" + "a" * 64,
            "state": "uploaded",
            "browser_download_url": "https://example.invalid/inventory.gz",
        }],
    }
    monkeypatch.setattr(module, "_json", lambda *_args, **_kwargs: release)
    monkeypatch.setattr(module, "_request", lambda *_args, **_kwargs: b"bad")

    with pytest.raises(module.RestoreError, match="SHA-256"):
        module._load_base_inventory(
            "o/r", ["data-one", release["tag_name"]], "token"
        )
