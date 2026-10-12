import importlib.util
from pathlib import Path


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
