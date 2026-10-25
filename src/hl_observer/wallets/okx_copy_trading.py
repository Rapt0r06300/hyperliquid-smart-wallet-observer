"""Read-only discovery and observation for OKX public Copy Trading leaders.

These responses are research/forward-observation inputs only. OKX's public
position history is not a full fee/cashflow ledger and is never economic proof.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


OKX_LEADER_ID_RE = re.compile(r"^[A-Fa-f0-9]{16,32}$")
PUBLIC_PATHS = {
    "ranks": "/api/v5/copytrading/public-lead-traders",
    "current": "/api/v5/copytrading/public-current-subpositions",
    "history": "/api/v5/copytrading/public-subpositions-history",
}
SORT_TYPES = ("pnl", "pnl_ratio", "win_ratio", "aum")


class OkxPublicApiError(RuntimeError):
    """An OKX public response was unavailable or failed validation."""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class OkxLeaderCandidate:
    unique_code: str
    nickname: str
    pnl_90d_usdt: float
    pnl_ratio_90d: float
    win_ratio: float
    aum_usdt: float
    lead_days: int
    instruments: tuple[str, ...]
    selection_score: float
    selection_reasons: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def identity(self) -> str:
        return f"okx:okx:{self.unique_code}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "venue": "okx",
            "network": "okx",
            "identity_kind": "public_leader_id",
            "native_account_id": self.unique_code,
            "identity": self.identity,
            "nickname": self.nickname,
            "pnl_90d_usdt": self.pnl_90d_usdt,
            "pnl_ratio_90d": self.pnl_ratio_90d,
            "win_ratio": self.win_ratio,
            "aum_usdt": self.aum_usdt,
            "lead_days": self.lead_days,
            "instruments": list(self.instruments),
            "discovery_score_only": self.selection_score,
            "selection_reasons": list(self.selection_reasons),
            "raw": self.raw,
        }


class OkxPublicCopyTradingClient:
    """Small bounded client for documented, unauthenticated OKX Copy Trading GETs."""

    def __init__(
        self,
        *,
        base_url: str = "https://www.okx.com",
        timeout_seconds: float = 12.0,
        min_request_interval_s: float = 0.42,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.okx.com", "openapi.okx.com", "us.okx.com", "eea.okx.com"}:
            raise ValueError("OKX base URL must be an HTTPS official OKX API host")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(2.0, float(timeout_seconds))
        self.min_request_interval_s = max(0.4, float(min_request_interval_s))
        self._last_request_at = 0.0

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if path not in PUBLIC_PATHS.values():
            raise ValueError("endpoint not on the OKX read-only public allowlist")
        query = urlencode({key: value for key, value in params.items() if value is not None})
        last_error: Exception | None = None
        for attempt in range(4):
            wait = self.min_request_interval_s - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            request = Request(
                f"{self.base_url}{path}?{query}",
                headers={"Accept": "application/json", "User-Agent": "AlinaSmartFlow-read-only/1.0"},
                method="GET",
            )
            self._last_request_at = time.monotonic()
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    if response.status != 200:
                        raise OkxPublicApiError(f"OKX HTTP {response.status} for {path}")
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise OkxPublicApiError(f"OKX returned a non-object response for {path}")
                code = str(payload.get("code", ""))
                if code == "0":
                    return payload
                last_error = OkxPublicApiError(f"OKX rejected {path}: code={code} msg={payload.get('msg')}")
                retryable = code in {"50000", "50011"} or code.startswith("5")
            except HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or exc.code >= 500
                if retryable and attempt < 3:
                    try:
                        delay = min(30.0, max(0.0, float(exc.headers.get("Retry-After", "0"))))
                    except (TypeError, ValueError):
                        delay = 0.0
                    time.sleep(max(delay, min(8.0, 0.5 * (2 ** attempt))))
                    continue
            except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError, OkxPublicApiError) as exc:
                last_error = exc
                retryable = not (isinstance(exc, OkxPublicApiError) and "non-object" in str(exc))
            if retryable and attempt < 3:
                time.sleep(min(8.0, 0.5 * (2 ** attempt)))
                continue
            break
        raise OkxPublicApiError(
            f"OKX public request failed after retries for {path}: "
            f"{type(last_error).__name__}: {last_error}"
        ) from last_error

    def discover_leaders(
        self,
        *,
        max_pages_per_sort: int = 25,
        sort_types: tuple[str, ...] = SORT_TYPES,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Read each ranking dimension under one frozen OKX dataVer per sort."""
        # Bound the scan but follow the API's reported pagination even if OKX
        # expands the public leaderboard beyond its currently observed 25 pages.
        max_pages = max(1, min(100, int(max_pages_per_sort)))
        candidates: dict[str, dict[str, Any]] = {}
        coverage: dict[str, dict[str, Any]] = {}
        for sort_type in sort_types:
            if sort_type not in SORT_TYPES:
                raise ValueError(f"unsupported OKX leaderboard sort: {sort_type}")
            version: str | None = None
            total_pages = 1
            pages_read = 0
            for page in range(1, max_pages + 1):
                payload = self._get(
                    PUBLIC_PATHS["ranks"],
                    {"instType": "SWAP", "sortType": sort_type, "state": "0", "page": page, "dataVer": version},
                )
                blocks = payload.get("data")
                if not isinstance(blocks, list) or not blocks or not isinstance(blocks[0], dict):
                    raise OkxPublicApiError(f"OKX leaderboard response has no page data for sort={sort_type}")
                block = blocks[0]
                version = version or str(block.get("dataVer") or "") or None
                try:
                    total_pages = max(1, int(block.get("totalPage") or 1))
                except (TypeError, ValueError):
                    total_pages = 1
                rows = block.get("ranks")
                if not isinstance(rows, list):
                    raise OkxPublicApiError(f"OKX leaderboard page is missing ranks for sort={sort_type}")
                pages_read += 1
                for row_index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    code = str(row.get("uniqueCode") or "").strip()
                    if not OKX_LEADER_ID_RE.fullmatch(code):
                        continue
                    item = candidates.setdefault(code, {"uniqueCode": code, "rank_observations": {}})
                    item["rank_observations"][sort_type] = {
                        "page": page,
                        "rank": len(rows) * (page - 1) + row_index + 1,
                        "dataVer": version,
                    }
                    # Keep the richest row; every sort snapshot is retained separately.
                    item["leader"] = row
                if page >= total_pages:
                    break
            coverage[sort_type] = {
                "dataVer": version,
                "pages_read": pages_read,
                "pages_reported": total_pages,
                "complete": pages_read >= total_pages,
            }
        return list(candidates.values()), {
            "venue": "okx",
            "instrument_type": "SWAP",
            "coverage_by_sort": coverage,
            "complete": all(item["complete"] for item in coverage.values()),
            "sort_types": list(sort_types),
        }

    def observe_leader(self, unique_code: str, *, limit: int = 100) -> dict[str, Any]:
        if not OKX_LEADER_ID_RE.fullmatch(str(unique_code or "")):
            raise ValueError("invalid OKX public leader uniqueCode")
        bounded_limit = str(max(1, min(100, int(limit))))
        requests = {
            "current_positions": {
                "path": PUBLIC_PATHS["current"],
                "params": {"instType": "SWAP", "uniqueCode": unique_code, "limit": bounded_limit},
            },
            "position_history": {
                "path": PUBLIC_PATHS["history"],
                "params": {"instType": "SWAP", "uniqueCode": unique_code, "limit": bounded_limit},
            },
        }
        results: dict[str, Any] = {}
        for name, request in requests.items():
            try:
                payload = self._get(request["path"], request["params"])
                rows = payload.get("data")
                if not isinstance(rows, list):
                    raise OkxPublicApiError(f"OKX {name} response data is not a list")
                results[name] = {
                    "request": request,
                    "rows": rows,
                    "row_count": len(rows),
                    "possibly_truncated_at_api_limit": len(rows) >= int(bounded_limit),
                    "response_sha256": _payload_hash(payload),
                    "response": payload,
                    "error": None,
                }
            except OkxPublicApiError as exc:
                results[name] = {
                    "request": request,
                    "rows": None,
                    "row_count": None,
                    "possibly_truncated_at_api_limit": None,
                    "response_sha256": None,
                    "response": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
        return {
            "venue": "okx",
            "network": "okx",
            "identity_kind": "public_leader_id",
            "native_account_id": unique_code,
            "observed_at_ms": int(time.time() * 1000),
            "current_positions": results["current_positions"],
            "position_history": results["position_history"],
            "endpoint_errors": {
                name: result["error"] for name, result in results.items() if result["error"]
            },
            "economic_proof_ready": False,
            "limitations": [
                "public position history is capped to the documented recent window",
                "endpoint does not expose complete fee, funding, cashflow, or follower execution evidence",
                "results are discovery/forward-observation only until an OKX SAFE replay pipeline is certified",
            ],
        }


def score_okx_leader(row: dict[str, Any]) -> tuple[float | None, tuple[str, ...]]:
    """Venue-local shortlist score; never comparable to another venue's score."""
    metrics = row.get("leader") if isinstance(row.get("leader"), dict) else row
    pnl = _finite(metrics.get("pnl"))
    roi = _finite(metrics.get("pnlRatio"))
    win = _finite(metrics.get("winRatio"))
    aum = _finite(metrics.get("aum"))
    try:
        lead_days = int(metrics.get("leadDays"))
    except (TypeError, ValueError):
        lead_days = None
    if None in (pnl, roi, win, aum, lead_days):
        return None, ("MORE_DATA_REQUIRED",)
    assert pnl is not None and roi is not None and win is not None and aum is not None and lead_days is not None
    if pnl <= 0 or roi <= 0 or aum <= 0 or win < 0 or win > 1 or lead_days < 90:
        return None, ("FAILED_PUBLIC_LEADER_SCREEN",)
    score = 100.0 * (
        0.50 * _clamp(roi / 0.50, 0.0, 1.0)
        + 0.30 * _clamp(win, 0.0, 1.0)
        + 0.20 * _clamp(lead_days / 365.0, 0.0, 1.0)
    )
    return round(score, 6), ("OKX_90D_PNL_AND_ROI_POSITIVE", "OKX_WIN_RATIO_AND_TENURE_SCREEN", "SHORTLIST_ONLY_NOT_PROOF")


__all__ = [
    "OKX_LEADER_ID_RE", "OkxLeaderCandidate", "OkxPublicApiError",
    "OkxPublicCopyTradingClient", "score_okx_leader",
]
