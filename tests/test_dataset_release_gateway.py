from __future__ import annotations

from pathlib import Path

import pytest

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


class _StreamResponse:
    def __init__(
        self,
        chunks: tuple[bytes, ...] = (b"abc", b"def"),
        *,
        status_code: int | None = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chunks = chunks
        if status_code is not None:
            self.status_code = status_code
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if getattr(self, "status_code", 200) >= 400:
            raise transport.requests.HTTPError(str(self.status_code))
        return None

    def iter_content(self, chunk_size):
        yield from self._chunks


def _install_stream_get(monkeypatch, response, seen: dict[str, object]) -> None:
    def fake_get(url, *, headers, timeout, stream, allow_redirects):
        seen["url"] = url
        seen["authorization"] = headers.get("Authorization")
        seen["range"] = headers.get("Range")
        seen["stream"] = stream
        seen["allow_redirects"] = allow_redirects
        return response

    monkeypatch.setattr(transport.requests, "get", fake_get)


def test_transport_https_stream_un_asset_prive_sans_gh(
    tmp_path: Path, monkeypatch
) -> None:
    """Un ancien mock sans status_code reste un 200 complet, jamais un append."""

    monkeypatch.setenv("GH_TOKEN", "token-stream-test")
    destination = tmp_path / "asset.bin"
    seen: dict[str, object] = {}
    response = _StreamResponse(status_code=None)
    _install_stream_get(monkeypatch, response, seen)
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


def test_transport_range_206_reprend_exactement_au_content_range(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-range")
    destination = tmp_path / "asset.bin"
    destination.write_bytes(b"abc")
    seen: dict[str, object] = {}
    _install_stream_get(
        monkeypatch,
        _StreamResponse(
            (b"def",),
            status_code=206,
            headers={"Content-Range": "bytes 3-5/6"},
        ),
        seen,
    )

    transport.download_release_asset(
        repository="exemple/donnees",
        asset_id=124,
        destination=destination,
    )

    assert seen["range"] == "bytes=3-"
    assert destination.read_bytes() == b"abcdef"


def test_transport_range_200_redemarre_un_partiel_sans_concatener(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-range")
    destination = tmp_path / "asset.bin"
    destination.write_bytes(b"PARTIEL-ANCIEN")
    seen: dict[str, object] = {}
    _install_stream_get(
        monkeypatch,
        _StreamResponse((b"nouveau",), status_code=200),
        seen,
    )

    transport.download_release_asset(
        repository="exemple/donnees",
        asset_id=125,
        destination=destination,
    )

    assert seen["range"] == f"bytes={len(b'PARTIEL-ANCIEN')}-"
    assert destination.read_bytes() == b"nouveau"


def test_transport_range_416_conserve_le_partiel_pour_hash_aval(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-range")
    destination = tmp_path / "asset.bin"
    destination.write_bytes(b"potentiellement-complet")
    seen: dict[str, object] = {}
    _install_stream_get(
        monkeypatch,
        _StreamResponse((), status_code=416),
        seen,
    )

    transport.download_release_asset(
        repository="exemple/donnees",
        asset_id=126,
        destination=destination,
    )

    assert destination.read_bytes() == b"potentiellement-complet"


def test_transport_range_206_sans_content_range_est_refuse_fail_closed(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-range")
    destination = tmp_path / "asset.bin"
    destination.write_bytes(b"abc")
    seen: dict[str, object] = {}
    _install_stream_get(
        monkeypatch,
        _StreamResponse((b"def",), status_code=206, headers={}),
        seen,
    )

    with pytest.raises(transport.GitHubTransportError, match="sans Content-Range"):
        transport.download_release_asset(
            repository="exemple/donnees",
            asset_id=127,
            destination=destination,
        )

    assert destination.read_bytes() == b"abc"


def test_transport_range_mismatch_ne_corrompt_pas_le_partiel(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "token-range")
    destination = tmp_path / "asset.bin"
    destination.write_bytes(b"abc")
    seen: dict[str, object] = {}
    _install_stream_get(
        monkeypatch,
        _StreamResponse(
            (b"DEF-NE-DOIT-PAS-ETRE-ECRIT",),
            status_code=206,
            headers={"Content-Range": "bytes 2-9/10"},
        ),
        seen,
    )

    with pytest.raises(transport.GitHubTransportError, match="attendu 3"):
        transport.download_release_asset(
            repository="exemple/donnees",
            asset_id=128,
            destination=destination,
        )

    assert destination.read_bytes() == b"abc"
