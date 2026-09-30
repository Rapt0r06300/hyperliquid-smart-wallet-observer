from __future__ import annotations

from pathlib import Path

import pytest

import hl_observer.datasets.release_gateway as gateway
from hl_observer.datasets.github_api_transport import GitHubTransportError
from hl_observer.datasets.github_release_bridge import DatasetBridgeError, ReleaseAsset


def asset(name="a.bin", *, asset_id=1, size=3, digest="sha256:abc") -> ReleaseAsset:
    return ReleaseAsset(asset_id=asset_id, name=name, size=size, digest=digest)


def test_gh_json_and_load_release(monkeypatch) -> None:
    with pytest.raises(DatasetBridgeError, match="Chemin GitHub absent"):
        gateway._gh_json([])
    monkeypatch.setattr(gateway, "get_json", lambda path: {"path": path})
    assert gateway._gh_json(["api", "repos/a/b"]) == {"path": "repos/a/b"}
    monkeypatch.setattr(gateway, "get_json", lambda path: (_ for _ in ()).throw(GitHubTransportError("offline")))
    with pytest.raises(DatasetBridgeError, match="offline"):
        gateway._gh_json(["api", "x"])

    monkeypatch.setattr(gateway, "_gh_json", lambda args: {"name": "release"})
    assert gateway._load_release("o/r", 5)["name"] == "release"
    monkeypatch.setattr(gateway, "_gh_json", lambda args: [])
    with pytest.raises(DatasetBridgeError, match="Réponse GitHub invalide"):
        gateway._load_release()


def test_download_asset_cached_redownload_invalid_id_and_transport_failure(tmp_path, monkeypatch) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"old")
    calls = []
    monkeypatch.setattr(gateway, "verify_asset", lambda path, a: calls.append(("verify", path.name)))
    assert gateway._download_asset(asset(), tmp_path, repository="o/r", force=False) == target
    assert calls == [("verify", "a.bin")]

    target.write_bytes(b"bad")
    verifies = {"n": 0}
    def verify(path, a):
        verifies["n"] += 1
        if verifies["n"] == 1:
            raise DatasetBridgeError("bad cache")
    monkeypatch.setattr(gateway, "verify_asset", verify)
    def download(**kwargs):
        kwargs["destination"].write_bytes(b"new")
    monkeypatch.setattr(gateway, "download_release_asset", download)
    assert gateway._download_asset(asset(), tmp_path, repository="o/r", force=False).read_bytes() == b"new"
    assert verifies["n"] == 2

    with pytest.raises(DatasetBridgeError, match="Identifiant GitHub invalide"):
        gateway._download_asset(asset(asset_id=0), tmp_path, repository="o/r", force=True)

    monkeypatch.setattr(gateway, "download_release_asset", lambda **k: (_ for _ in ()).throw(GitHubTransportError("down")))
    with pytest.raises(DatasetBridgeError, match="Téléchargement GitHub échoué"):
        gateway._download_asset(asset(name="b.bin"), tmp_path, repository="o/r", force=True)
    assert not (tmp_path / "b.bin.part").exists()


def test_parse_asset_page_skips_invalid_and_normalizes() -> None:
    with pytest.raises(DatasetBridgeError, match="liste des fichiers"):
        gateway.parse_asset_page({})
    rows = gateway.parse_asset_page([
        None,
        {},
        {"name": "a", "id": "2", "size": "3", "digest": "sha256:ff"},
        {"name": "b", "id": None, "size": None, "digest": None},
    ])
    assert [(r.name, r.asset_id, r.size, r.digest) for r in rows] == [
        ("a", 2, 3, "sha256:ff"), ("b", 0, 0, "")
    ]


def test_list_all_release_assets_paginates_duplicates_and_guard(monkeypatch) -> None:
    pages = {
        1: [{"name": "a", "id": 1, "size": 1}, {"name": "b", "id": 2, "size": 2}],
        2: [{"name": "c", "id": 3, "size": 3}],
    }
    def gh(args):
        text = args[-1]
        page = int(text.split("page=")[-1])
        return pages[page]
    monkeypatch.setattr(gateway, "_gh_json", gh)
    result = gateway.list_all_release_assets("o/r", 1, per_page=2)
    assert list(result) == ["a", "b", "c"]

    pages[2] = [{"name": "a", "id": 99, "size": 1}]
    with pytest.raises(DatasetBridgeError, match="même nom"):
        gateway.list_all_release_assets("o/r", 1, per_page=2)

    monkeypatch.setattr(gateway, "_gh_json", lambda args: [{"name": f"asset-{args[-1]}", "id": 1, "size": 1}])
    with pytest.raises(DatasetBridgeError, match="Pagination GitHub anormalement longue"):
        gateway.list_all_release_assets("o/r", 1, per_page=1)


def test_ensure_release_metadata_required_optional_and_missing(tmp_path, monkeypatch) -> None:
    release = {"name": "R"}
    names = list(gateway.CORE_METADATA_ASSETS) + list(gateway.OPTIONAL_METADATA_ASSETS)
    assets = {name: asset(name=name, asset_id=i + 1) for i, name in enumerate(names)}
    monkeypatch.setattr(gateway, "_load_release", lambda *a, **k: release)
    monkeypatch.setattr(gateway, "list_all_release_assets", lambda *a, **k: assets)
    monkeypatch.setattr(gateway, "dataset_metadata_dir", lambda root: tmp_path / "metadata")
    downloaded = []
    monkeypatch.setattr(gateway, "_download_asset", lambda a, dest, **k: (downloaded.append(a.name) or dest / a.name))
    got_release, got_assets, metadata = gateway.ensure_release_metadata(tmp_path, repository="o/r", release_id=5, force=True)
    assert got_release is release and got_assets is assets
    assert metadata.is_dir()
    assert downloaded == names

    missing_assets = {name: assets[name] for name in gateway.OPTIONAL_METADATA_ASSETS}
    monkeypatch.setattr(gateway, "list_all_release_assets", lambda *a, **k: missing_assets)
    with pytest.raises(DatasetBridgeError, match="fichiers de contrôle"):
        gateway.ensure_release_metadata(tmp_path)


def test_build_release_status_paths_and_counts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gateway, "_load_release", lambda *a, **k: {
        "name": "R", "tag_name": "v1", "draft": 1, "published_at": "now"
    })
    assets = {
        "a": asset(name="a", size=10, digest="sha256:aa"),
        "b": asset(name="b", asset_id=2, size=20, digest=""),
    }
    monkeypatch.setattr(gateway, "list_all_release_assets", lambda *a, **k: assets)
    monkeypatch.setattr(gateway, "dataset_metadata_dir", lambda root: root / "meta")
    monkeypatch.setattr(gateway, "dataset_asset_cache_dir", lambda root: root / "cache")
    monkeypatch.setattr(gateway, "dataset_materialized_dir", lambda root: root / "materialized")
    row = gateway.build_release_status(tmp_path, repository="o/r", release_id=9)
    assert row["repository"] == "o/r" and row["release_id"] == 9
    assert row["release_name"] == "R" and row["tag_name"] == "v1" and row["draft"] is True
    assert row["asset_count"] == 2 and row["asset_bytes"] == 30 and row["assets_with_sha256"] == 1
    assert row["local_metadata_dir"].endswith("meta")
    assert row["local_asset_cache_dir"].endswith("cache")
    assert row["local_materialized_dir"].endswith("materialized")
