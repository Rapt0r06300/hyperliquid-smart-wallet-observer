from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

import hl_observer.datasets.github_api_transport as transport


def test_token_headers_url_and_status_helpers(monkeypatch) -> None:
    for key in (transport.DATASET_TOKEN_ENV, "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert transport.github_token() is None
    monkeypatch.setenv("GITHUB_TOKEN", " generic ")
    monkeypatch.setenv("GH_TOKEN", " gh ")
    monkeypatch.setenv(transport.DATASET_TOKEN_ENV, " dedicated ")
    assert transport.github_token() == "dedicated"
    assert transport._headers()["Authorization"] == "Bearer dedicated"
    assert transport._headers(accept="application/octet-stream")["Accept"] == "application/octet-stream"
    assert transport._api_url("repos/a/b") == "https://api.github.com/repos/a/b"
    assert transport._api_url("https://example.test/x") == "https://example.test/x"
    assert transport._response_status_code(object()) == 200
    assert transport._response_status_code(SimpleNamespace(status_code="206")) == 206
    assert transport._response_status_code(SimpleNamespace(status_code="bad")) == 200
    assert transport._content_range_start(
        SimpleNamespace(headers={"Content-Range": "bytes 10-19/100"})
    ) == 10
    assert transport._content_range_start(SimpleNamespace(headers={"Content-Range": "bad"})) is None


def test_get_json_fallback_https_and_errors(monkeypatch) -> None:
    monkeypatch.setattr(transport, "github_token", lambda: None)
    monkeypatch.setattr(transport, "_gh_json_fallback", lambda path: {"fallback": path})
    assert transport.get_json("x") == {"fallback": "x"}

    monkeypatch.setattr(transport, "github_token", lambda: "token")

    class Response:
        def raise_for_status(self) -> None:
            return None
        def json(self):
            return {"ok": 1}

    monkeypatch.setattr(transport.requests, "get", lambda *args, **kwargs: Response())
    assert transport.get_json("x") == {"ok": 1}
    monkeypatch.setattr(
        transport.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )
    with pytest.raises(transport.GitHubTransportError, match="ConnectionError"):
        transport.get_json("x")


def test_gh_json_fallback_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(transport, "_gh_path", lambda: None)
    with pytest.raises(transport.GitHubTransportError, match="GitHub CLI"):
        transport._gh_json_fallback("x")
    monkeypatch.setattr(transport, "_gh_path", lambda: "gh")
    monkeypatch.setattr(
        transport.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stderr="denied", stdout=""),
    )
    with pytest.raises(transport.GitHubTransportError, match="code 2"):
        transport._gh_json_fallback("x")


class _StreamResponse:
    def __init__(self, *, status=200, headers=None, chunks=(), raise_exc=None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self.chunks = list(chunks)
        self.raise_exc = raise_exc

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self) -> None:
        if self.raise_exc:
            raise self.raise_exc

    def iter_content(self, chunk_size):
        return iter(self.chunks)


def test_download_release_asset_restart_append_range_and_416(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(transport, "github_token", lambda: "token")
    destination = tmp_path / "asset.part"
    destination.write_bytes(b"old")
    response = _StreamResponse(status=200, chunks=[b"new", b"data"])
    monkeypatch.setattr(transport.requests, "get", lambda *args, **kwargs: response)
    transport.download_release_asset(repository="o/r", asset_id=6, destination=destination)
    assert destination.read_bytes() == b"newdata"

    destination.write_bytes(b"abc")
    response = _StreamResponse(
        status=206,
        headers={"Content-Range": "bytes 3-5/6"},
        chunks=[b"def"],
    )
    monkeypatch.setattr(transport.requests, "get", lambda *args, **kwargs: response)
    transport.download_release_asset(repository="o/r", asset_id=7, destination=destination)
    assert destination.read_bytes() == b"abcdef"

    destination.write_bytes(b"abc")
    response = _StreamResponse(status=206, headers={}, chunks=[b"def"])
    monkeypatch.setattr(transport.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(transport.GitHubTransportError, match="sans Content-Range"):
        transport.download_release_asset(repository="o/r", asset_id=7, destination=destination)
    assert destination.read_bytes() == b"abc"

    response = _StreamResponse(status=416)
    monkeypatch.setattr(transport.requests, "get", lambda *args, **kwargs: response)
    transport.download_release_asset(repository="o/r", asset_id=8, destination=destination)
    assert destination.read_bytes() == b"abc"
