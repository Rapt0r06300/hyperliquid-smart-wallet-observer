from __future__ import annotations

import pytest

import hl_observer.datasets.release_gateway as gateway
from hl_observer.datasets.github_api_transport import GitHubTransportError
from hl_observer.datasets.github_release_bridge import DatasetBridgeError, ReleaseAsset


def _asset(name="a.bin", *, asset_id=1, size=3, digest="sha256:abc") -> ReleaseAsset:
    return ReleaseAsset(asset_id=asset_id, name=name, size=size, digest=digest)


def test_gateway_json_parse_pagination_and_status(tmp_path, monkeypatch) -> None:
    with pytest.raises(DatasetBridgeError, match="Chemin GitHub absent"):
        gateway._gh_json([])
    monkeypatch.setattr(gateway, "get_json", lambda path: {"path": path})
    assert gateway._gh_json(["api", "repos/a/b"]) == {"path": "repos/a/b"}
    monkeypatch.setattr(
        gateway,
        "get_json",
        lambda path: (_ for _ in ()).throw(GitHubTransportError("offline")),
    )
    with pytest.raises(DatasetBridgeError, match="offline"):
        gateway._gh_json(["api", "x"])

    with pytest.raises(DatasetBridgeError, match="liste des fichiers"):
        gateway.parse_asset_page({})
    rows = gateway.parse_asset_page([
        None,
        {},
        {"name": "a", "id": "2", "size": "3", "digest": "sha256:ff"},
    ])
    assert rows[0].name == "a" and rows[0].asset_id == 2 and rows[0].size == 3

    pages = {
        1: [{"name": "a", "id": 1, "size": 1}, {"name": "b", "id": 2, "size": 2}],
        2: [{"name": "c", "id": 3, "size": 3}],
    }

    def gh(args):
        return pages[int(args[-1].split("page=")[-1])]

    monkeypatch.setattr(gateway, "_gh_json", gh)
    assert list(gateway.list_all_release_assets("o/r", 1, per_page=2)) == ["a", "b", "c"]

    monkeypatch.setattr(gateway, "_load_release", lambda *a, **k: {
        "name": "R", "tag_name": "v1", "draft": 1, "published_at": "now"
    })
    assets = {
        "a": _asset(name="a", size=10, digest="sha256:aa"),
        "b": _asset(name="b", asset_id=2, size=20, digest=""),
    }
    monkeypatch.setattr(gateway, "list_all_release_assets", lambda *a, **k: assets)
    row = gateway.build_release_status(tmp_path, repository="o/r", release_id=9)
    assert row["asset_count"] == 2 and row["asset_bytes"] == 30
    assert row["assets_with_sha256"] == 1 and row["draft"] is True
