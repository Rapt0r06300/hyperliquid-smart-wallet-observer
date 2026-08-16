from __future__ import annotations

from hl_observer.datasets import release_gateway


def _asset(asset_id: int, name: str) -> dict[str, object]:
    return {
        "id": asset_id,
        "name": name,
        "size": asset_id * 10,
        "digest": "sha256:" + (str(asset_id % 10) * 64),
    }


def test_parse_asset_page_lit_un_hash() -> None:
    rows = release_gateway.parse_asset_page([_asset(1, "a.bin")])
    assert len(rows) == 1
    assert rows[0].name == "a.bin"
    assert rows[0].sha256 == "1" * 64


def test_list_all_release_assets_lit_plusieurs_pages(monkeypatch) -> None:
    calls: list[str] = []

    def fake_gh_json(arguments):
        url = arguments[-1]
        calls.append(url)
        if "page=1" in url:
            return [_asset(1, "a.bin"), _asset(2, "b.bin")]
        if "page=2" in url:
            return [_asset(3, "c.bin")]
        raise AssertionError(url)

    monkeypatch.setattr(release_gateway, "_gh_json", fake_gh_json)
    assets = release_gateway.list_all_release_assets(
        "exemple/donnees", 42, per_page=2
    )
    assert set(assets) == {"a.bin", "b.bin", "c.bin"}
    assert len(calls) == 2


def test_list_all_release_assets_refuse_deux_noms_identiques(monkeypatch) -> None:
    def fake_gh_json(arguments):
        url = arguments[-1]
        if "page=1" in url:
            return [_asset(1, "meme.bin"), _asset(2, "autre.bin")]
        return [_asset(3, "meme.bin")]

    monkeypatch.setattr(release_gateway, "_gh_json", fake_gh_json)
    try:
        release_gateway.list_all_release_assets("exemple/donnees", 42, per_page=2)
    except release_gateway.DatasetBridgeError as exc:
        assert "même nom" in str(exc)
    else:
        raise AssertionError("Le doublon aurait dû être refusé")
