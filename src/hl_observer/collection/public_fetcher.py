"""Public read-only fetcher with cache and provenance hooks.

The network transport is injected so tests and agents can verify behaviour
without making live requests. This layer fetches public pages only; it does not
log in, bypass captchas, place orders, sign, or mutate any external service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Callable
from urllib.parse import urlparse

from hl_observer.sources.models import FetchProvenance, SourceDefinition, SourceKind
from hl_observer.sources.registry import SourceRegistry
from hl_observer.storage.raw_store import RawStore, make_raw_event
from hl_observer.storage.run_context import RunContext


FetchTransport = Callable[[str], tuple[int, dict[str, str], str]]


@dataclass(frozen=True, slots=True)
class PublicFetchRequest:
    url: str
    source_id: str
    cache_ttl_ms: int = 30_000
    context: RunContext = RunContext.LIVE


@dataclass(frozen=True, slots=True)
class PublicFetchResult:
    ok: bool
    url: str
    source_id: str
    status_code: int | None
    body: str | None
    raw_hash: str | None
    from_cache: bool
    fetched_at_ms: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
    read_only: bool = True
    external_action: bool = False


class MemoryFetchCache:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, PublicFetchResult]] = {}

    def get(self, url: str, *, now_ms: int, ttl_ms: int) -> PublicFetchResult | None:
        entry = self._entries.get(url)
        if entry is None:
            return None
        stored_at, result = entry
        if now_ms - stored_at > ttl_ms:
            return None
        return PublicFetchResult(
            ok=result.ok,
            url=result.url,
            source_id=result.source_id,
            status_code=result.status_code,
            body=result.body,
            raw_hash=result.raw_hash,
            from_cache=True,
            fetched_at_ms=now_ms,
            warnings=result.warnings,
        )

    def put(self, result: PublicFetchResult) -> None:
        self._entries[result.url] = (result.fetched_at_ms, result)


def fetch_public_page(
    request: PublicFetchRequest,
    *,
    now_ms: int,
    transport: FetchTransport,
    cache: MemoryFetchCache | None = None,
    registry: SourceRegistry | None = None,
    raw_store: RawStore | None = None,
) -> PublicFetchResult:
    warnings: list[str] = []
    if not _is_public_http_url(request.url):
        return PublicFetchResult(
            ok=False,
            url=request.url,
            source_id=request.source_id,
            status_code=None,
            body=None,
            raw_hash=None,
            from_cache=False,
            fetched_at_ms=now_ms,
            warnings=("INVALID_PUBLIC_URL",),
        )
    if registry is not None and not registry.is_registered(request.source_id):
        registry.register(
            SourceDefinition(
                source_id=request.source_id,
                kind=SourceKind.PUBLIC_SCRAPE,
                endpoint_or_channel=request.url,
                description="Public read-only page",
            )
        )
    if cache is not None:
        cached = cache.get(request.url, now_ms=now_ms, ttl_ms=request.cache_ttl_ms)
        if cached is not None:
            return cached

    try:
        status_code, headers, body = transport(request.url)
    except Exception as exc:  # noqa: BLE001 - transport boundary converts to source health.
        result = PublicFetchResult(
            ok=False,
            url=request.url,
            source_id=request.source_id,
            status_code=None,
            body=None,
            raw_hash=None,
            from_cache=False,
            fetched_at_ms=now_ms,
            warnings=(f"FETCH_FAILED:{exc.__class__.__name__}",),
        )
        _record_provenance(registry, request, result, now_ms=now_ms, error=str(exc))
        return result

    if status_code in {401, 403}:
        warnings.append("PUBLIC_ACCESS_DENIED")
    if "retry-after" in {k.lower() for k in headers}:
        warnings.append("RETRY_AFTER_PRESENT")
    if _looks_like_login_or_captcha(body):
        warnings.append("LOGIN_OR_CAPTCHA_PAGE")

    raw_hash = sha256(str(body or "").encode("utf-8", errors="ignore")).hexdigest()
    ok = 200 <= int(status_code) < 300 and "LOGIN_OR_CAPTCHA_PAGE" not in warnings
    result = PublicFetchResult(
        ok=ok,
        url=request.url,
        source_id=request.source_id,
        status_code=int(status_code),
        body=body if ok else None,
        raw_hash=raw_hash,
        from_cache=False,
        fetched_at_ms=now_ms,
        warnings=tuple(warnings),
    )
    _record_provenance(registry, request, result, now_ms=now_ms, error=None if ok else ",".join(warnings) or None)
    if raw_store is not None:
        raw_store.put(
            make_raw_event(
                source_id=request.source_id,
                kind="public_scrape",
                payload={"url": request.url, "status_code": status_code, "body": body},
                fetched_at_ms=now_ms,
                context=request.context,
                request_id=_request_id(request.url, now_ms),
                item_count=1 if ok else 0,
            )
        )
    if cache is not None and ok:
        cache.put(result)
    return result


def _record_provenance(
    registry: SourceRegistry | None,
    request: PublicFetchRequest,
    result: PublicFetchResult,
    *,
    now_ms: int,
    error: str | None,
) -> None:
    if registry is None:
        return
    registry.record_fetch(
        FetchProvenance(
            source_id=request.source_id,
            request_id=_request_id(request.url, now_ms),
            fetched_at_ms=now_ms,
            ok=result.ok,
            raw_hash=result.raw_hash,
            item_count=1 if result.ok else 0,
            data_quality="OK" if result.ok else "BAD",
            error=error,
        )
    )


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_login_or_captcha(body: str | None) -> bool:
    lowered = str(body or "").lower()
    return any(token in lowered for token in ("captcha", "sign in", "log in", "requires login"))


def _request_id(url: str, now_ms: int) -> str:
    return "public:" + sha256(f"{url}|{now_ms}".encode("utf-8")).hexdigest()[:24]


__all__ = [
    "MemoryFetchCache",
    "PublicFetchRequest",
    "PublicFetchResult",
    "fetch_public_page",
]
