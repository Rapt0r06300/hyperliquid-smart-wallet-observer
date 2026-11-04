from __future__ import annotations

import requests

from hl_observer.datasets import github_api_transport as transport


class _Response:
    def __init__(self, status_code: int, payload: object = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self._payload

    def close(self) -> None:
        self.closed = True


def test_get_json_retries_transient_release_response_and_returns_only_final_success(monkeypatch):
    responses = iter([
        _Response(429, headers={"Retry-After": "0"}),
        _Response(503),
        _Response(200, {"release": "safe"}),
    ])
    sleeps: list[float] = []
    monkeypatch.setenv(transport.DATASET_TOKEN_ENV, "runtime-only-token")
    monkeypatch.setattr(transport.requests, "get", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(transport.time, "sleep", sleeps.append)

    assert transport.get_json("repos/example/releases/1") == {"release": "safe"}
    assert sleeps == [0.0, 2.0]


def test_get_json_fails_closed_after_bounded_transient_responses(monkeypatch):
    responses = iter([_Response(502) for _ in range(transport.MAX_TRANSIENT_ATTEMPTS)])
    sleeps: list[float] = []
    monkeypatch.setenv(transport.DATASET_TOKEN_ENV, "runtime-only-token")
    monkeypatch.setattr(transport.requests, "get", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(transport.time, "sleep", sleeps.append)

    try:
        transport.get_json("repos/example/releases/1")
    except transport.GitHubTransportError as exc:
        assert "HTTP 502" in str(exc)
    else:
        raise AssertionError("a transient release response must never be accepted as success")
    assert len(sleeps) == transport.MAX_TRANSIENT_ATTEMPTS - 1
