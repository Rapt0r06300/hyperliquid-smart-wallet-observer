from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import hl_observer.datasets.github_api_transport as transport


def test_github_token_priority_and_headers(monkeypatch) -> None:
    for key in (transport.DATASET_TOKEN_ENV, "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert transport.github_token() is None
    monkeypatch.setenv("GITHUB_TOKEN", " generic ")
    assert transport.github_token() == "generic"
    monkeypatch.setenv("GH_TOKEN", " gh ")
    assert transport.github_token() == "gh"
    monkeypatch.setenv(transport.DATASET_TOKEN_ENV, " dedicated ")
    assert transport.github_token() == "dedicated"
    headers = transport._headers()
    assert headers["Authorization"] == "Bearer dedicated"
    assert headers["Accept"] == "application/vnd.github+json"
    assert transport._headers(accept="application/octet-stream")["Accept"] == "application/octet-stream"


def test_api_url_and_gh_path(monkeypatch) -> None:
    assert transport._api_url("repos/a/b") == "https://api.github.com/repos/a/b"
    assert transport._api_url("/repos/a/b") == "https://api.github.com/repos/a/b"
    assert transport._api_url("https://example.test/x") == "https://example.test/x"
    monkeypatch.setattr(transport.shutil, "which", lambda name: "/bin/gh" if name == "gh" else None)
    assert transport._gh_path() == "/bin/gh"


def test_gh_json_fallback_missing_cli_failure_invalid_json_and_success(monkeypatch) -> None:
    monkeypatch.setattr(transport, "_gh_path", lambda: None)
    with pytest.raises(transport.GitHubTransportError, match="GitHub CLI"):
        transport._gh_json_fallback("x")

    monkeypatch.setattr(transport, "_gh_path", lambda: "gh")
    monkeypatch.setattr(transport.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2, stderr="denied", stdout=""))
    with pytest.raises(transport.GitHubTransportError, match="code 2"):
        transport._gh_json_fallback("x")

    monkeypatch.setattr(transport.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout="bad"))
    with pytest.raises(transport.GitHubTransportError, match="JSON illisible"):
        transport._gh_json_fallback("x")

    monkeypatch.setattr(transport.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout='{"ok":1}'))
    assert transport._gh_json_fallback("x") == {"ok": 1}


def test_get_json_fallback_https_success_request_error_and_bad_json(monkeypatch) -> None:
    monkeypatch.setattr(transport, "github_token", lambda: None)
    monkeypatch.setattr(transport, "_gh_json_fallback", lambda path: {"fallback": path})
    assert transport.get_json("x") == {"fallback": "x"}

    monkeypatch.setattr(transport, "github_token", lambda: "token")
    class Response:
        def raise_for_status(self): return None
        def json(self): return {"ok": 1}
    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: Response())
    assert transport.get_json("x") == {"ok": 1}

    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline")))
    with pytest.raises(transport.GitHubTransportError, match="ConnectionError"):
        transport.get_json("x")

    class BadJson(Response):
        def json(self): raise ValueError("bad")
    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: BadJson())
    with pytest.raises(transport.GitHubTransportError, match="JSON illisible"):
        transport.get_json("x")


def test_download_with_gh_missing_success_and_failure(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "asset.bin"
    monkeypatch.setattr(transport, "_gh_path", lambda: None)
    with pytest.raises(transport.GitHubTransportError, match="CLI"):
        transport._download_with_gh("x", dest)

    monkeypatch.setattr(transport, "_gh_path", lambda: "gh")
    def success(command, stdout, stderr):
        stdout.write(b"payload")
        return SimpleNamespace(returncode=0, stderr=b"")
    monkeypatch.setattr(transport.subprocess, "run", success)
    transport._download_with_gh("x", dest)
    assert dest.read_bytes() == b"payload"

    def failure(command, stdout, stderr):
        stdout.write(b"partial")
        return SimpleNamespace(returncode=3, stderr=b"denied")
    monkeypatch.setattr(transport.subprocess, "run", failure)
    with pytest.raises(transport.GitHubTransportError, match="code 3"):
        transport._download_with_gh("x", dest)
    assert not dest.exists()


def test_response_status_and_content_range_helpers() -> None:
    assert transport._response_status_code(object()) == 200
    assert transport._response_status_code(SimpleNamespace(status_code="206")) == 206
    assert transport._response_status_code(SimpleNamespace(status_code="bad")) == 200
    assert transport._content_range_start(SimpleNamespace(headers={"Content-Range": "bytes 10-19/100"})) == 10
    assert transport._content_range_start(SimpleNamespace(headers={"content-range": " bytes 3-9/* "})) == 3
    assert transport._content_range_start(SimpleNamespace(headers={"Content-Range": "bad"})) is None
    assert transport._content_range_start(object()) is None


class StreamResponse:
    def __init__(self, *, status=200, headers=None, chunks=(), raise_exc=None):
        self.status_code = status
        self.headers = headers or {}
        self.chunks = list(chunks)
        self.raise_exc = raise_exc
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def raise_for_status(self):
        if self.raise_exc: raise self.raise_exc
    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        return iter(self.chunks)


def test_download_release_asset_gh_fallback_and_200_restart(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "asset.part"
    destination.write_bytes(b"old")
    monkeypatch.setattr(transport, "github_token", lambda: None)
    calls = []
    monkeypatch.setattr(transport, "_download_with_gh", lambda path, dest: (calls.append((path, dest)) or dest.write_bytes(b"gh")))
    transport.download_release_asset(repository="o/r", asset_id=5, destination=destination)
    assert destination.read_bytes() == b"gh"
    assert calls[0][0] == "repos/o/r/releases/assets/5"

    monkeypatch.setattr(transport, "github_token", lambda: "token")
    destination.write_bytes(b"partial")
    response = StreamResponse(status=200, chunks=[b"new", b"", b"data"])
    captured = {}
    def getter(url, **kwargs):
        captured.update(url=url, **kwargs)
        return response
    monkeypatch.setattr(transport.requests, "get", getter)
    transport.download_release_asset(repository="o/r", asset_id=6, destination=destination, chunk_bytes=1)
    assert destination.read_bytes() == b"newdata"
    assert captured["headers"]["Range"] == f"bytes={len(b'partial')}-"
    assert response.chunk_size == 64 * 1024


def test_download_release_asset_206_append_validates_range(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(transport, "github_token", lambda: "token")
    destination = tmp_path / "asset.part"
    destination.write_bytes(b"abc")
    response = StreamResponse(status=206, headers={"Content-Range": "bytes 3-5/6"}, chunks=[b"def"])
    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: response)
    transport.download_release_asset(repository="o/r", asset_id=7, destination=destination)
    assert destination.read_bytes() == b"abcdef"

    destination.write_bytes(b"abc")
    response = StreamResponse(status=206, headers={}, chunks=[b"def"])
    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: response)
    with pytest.raises(transport.GitHubTransportError, match="sans Content-Range"):
        transport.download_release_asset(repository="o/r", asset_id=7, destination=destination)
    assert destination.read_bytes() == b"abc"

    response = StreamResponse(status=206, headers={"Content-Range": "bytes 1-2/3"}, chunks=[b"x"])
    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: response)
    with pytest.raises(transport.GitHubTransportError, match="attendu 3"):
        transport.download_release_asset(repository="o/r", asset_id=7, destination=destination)


def test_download_release_asset_416_and_request_failure_keep_partial(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(transport, "github_token", lambda: "token")
    destination = tmp_path / "asset.part"
    destination.write_bytes(b"abc")
    response = StreamResponse(status=416)
    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: response)
    transport.download_release_asset(repository="o/r", asset_id=8, destination=destination)
    assert destination.read_bytes() == b"abc"

    response = StreamResponse(status=500, raise_exc=requests.HTTPError("bad"))
    monkeypatch.setattr(transport.requests, "get", lambda *a, **k: response)
    with pytest.raises(transport.GitHubTransportError, match="HTTPError"):
        transport.download_release_asset(repository="o/r", asset_id=8, destination=destination)
    assert destination.read_bytes() == b"abc"
