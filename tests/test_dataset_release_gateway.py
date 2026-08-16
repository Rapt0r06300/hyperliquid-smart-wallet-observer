from __future__ import annotations

from pathlib import Path

from hl_observer.datasets import github_api_transport as transport
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


def test_transport_https_utilise_le_token_runtime_sans_appeler_gh(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-test-ne-doit-pas-sortir")
    seen: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": 371149058, "name": "test"}

    def fake_get(url, *, headers, timeout, **kwargs):
        seen["url"] = url
        seen["authorization"] = headers.get("Authorization")
        seen["timeout"] = timeout
        return FakeResponse()

    def forbidden_gh(_path):
        raise AssertionError("gh ne doit pas être utilisé quand GH_TOKEN existe")

    monkeypatch.setattr(transport.requests, "get", fake_get)
    monkeypatch.setattr(transport, "_gh_json_fallback", forbidden_gh)

    payload = transport.get_json("repos/exemple/donnees/releases/371149058")
    assert payload["id"] == 371149058
    assert str(seen["url"]).startswith("https://api.github.com/")
    assert seen["authorization"] == "Bearer token-test-ne-doit-pas-sortir"


def test_transport_https_stream_un_asset_prive_sans_gh(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-stream-test")
    destination = tmp_path / "asset.bin"
    seen: dict[str, object] = {}

    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            seen["chunk_size"] = chunk_size
            yield b"abc"
            yield b"def"

    def fake_get(url, *, headers, timeout, stream, allow_redirects):
        seen["url"] = url
        seen["authorization"] = headers.get("Authorization")
        seen["stream"] = stream
        seen["allow_redirects"] = allow_redirects
        return FakeStreamResponse()

    monkeypatch.setattr(transport.requests, "get", fake_get)
    monkeypatch.setattr(
        transport,
        "_download_with_gh",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("gh ne doit pas être utilisé avec GH_TOKEN")
        ),
    )

    transport.download_release_asset(
        repository="exemple/donnees",
        asset_id=123,
        destination=destination,
        chunk_bytes=64 * 1024,
    )
    assert destination.read_bytes() == b"abcdef"
    assert seen["authorization"] == "Bearer token-stream-test"
    assert seen["stream"] is True
    assert seen["allow_redirects"] is True
