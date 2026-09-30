#!/usr/bin/env python3
"""Build current GitHub-hosted read-only source runtime evidence.

The receipt is deliberately conservative: network failure becomes DEGRADED,
never a fabricated HEALTHY state.  It never authenticates and never touches
trading endpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

VENUES = ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")
NATIVE_VENUES = ("bybit", "okx", "gate", "bitget")
CAPABILITIES = (
    "trades",
    "bbo",
    "l2",
    "clock_sync",
    "recovery",
    "replay_adapter",
    "sequence_integrity",
    "venue_status",
    "official_archive",
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, object] | None = None,
    timeout: float = 6.0,
) -> object:
    data = None
    headers = {"User-Agent": "alina-source-capability-probe/1"}
    if payload is not None:
        data = json.dumps(dict(payload)).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8-sig"))


def _probe_hyperliquid(request_json: Callable[..., object]) -> tuple[bool, str]:
    try:
        payload = request_json(
            "https://api.hyperliquid.xyz/info",
            method="POST",
            payload={"type": "meta"},
        )
        universe = payload.get("universe") if isinstance(payload, dict) else None
        if not isinstance(universe, list) or not universe:
            return False, "HYPERLIQUID_META_EMPTY"
        return True, f"HYPERLIQUID_META_OK:{len(universe)}"
    except Exception as exc:  # network evidence is fail-closed
        return False, f"HYPERLIQUID_UNAVAILABLE:{type(exc).__name__}"


def _probe_binance(request_json: Callable[..., object]) -> tuple[bool, str]:
    try:
        payload = request_json("https://fapi.binance.com/fapi/v1/time")
        server_time = payload.get("serverTime") if isinstance(payload, dict) else None
        if not isinstance(server_time, int) or server_time <= 0:
            return False, "BINANCE_TIME_INVALID"
        return True, "BINANCE_TIME_OK"
    except Exception as exc:  # network evidence is fail-closed
        return False, f"BINANCE_UNAVAILABLE:{type(exc).__name__}"


def _load_native_heartbeat(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def build_receipt(
    *,
    native_heartbeat: Path,
    github_sha: str,
    github_run_id: str,
    request_json: Callable[..., object] = _request_json,
    now_utc: str | None = None,
) -> dict[str, object]:
    observed_at = now_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    hb = _load_native_heartbeat(native_heartbeat)
    last_event = hb.get("last_event_ms") if isinstance(hb.get("last_event_ms"), dict) else {}

    hl_ok, hl_reason = _probe_hyperliquid(request_json)
    bin_ok, bin_reason = _probe_binance(request_json)

    venues: dict[str, object] = {}
    for venue, ok, reason in (
        ("hyperliquid", hl_ok, hl_reason),
        ("binance", bin_ok, bin_reason),
    ):
        runtime = "HEALTHY" if ok else "DEGRADED"
        venues[venue] = {
            "runtime_status": runtime,
            "reason": reason,
            "observed_at_utc": observed_at,
            "network_observed": ok,
            "capability_runtime": {name: runtime for name in CAPABILITIES},
        }

    for venue in NATIVE_VENUES:
        event_ms = int(last_event.get(venue) or 0)
        ok = event_ms > 0
        runtime = "HEALTHY" if ok else "DEGRADED"
        reason = (
            f"NATIVE_EVENT_OBSERVED:{event_ms}"
            if ok
            else "NATIVE_EVENT_NOT_OBSERVED_ON_GITHUB_HOSTED_SMOKE"
        )
        venues[venue] = {
            "runtime_status": runtime,
            "reason": reason,
            "observed_at_utc": observed_at,
            "network_observed": ok,
            "last_event_ms": event_ms,
            "capability_runtime": {name: runtime for name in CAPABILITIES},
        }

    body: dict[str, object] = {
        "schema_version": "alina.source_capability_runtime.v1",
        "generated_at_utc": observed_at,
        "github_sha": github_sha,
        "github_run_id": github_run_id,
        "runner_kind": "github-hosted",
        "paper_read_only": True,
        "real_execution": False,
        "native_heartbeat_present": bool(hb),
        "native_records_written": int(hb.get("records_written") or 0),
        "venues": venues,
    }
    body["receipt_digest"] = _digest(body)
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-heartbeat", required=True)
    parser.add_argument("--output", default="docs/source-capability-runtime.json")
    parser.add_argument("--github-sha", default=os.environ.get("GITHUB_SHA", "unknown"))
    parser.add_argument("--github-run-id", default=os.environ.get("GITHUB_RUN_ID", "unknown"))
    args = parser.parse_args()

    receipt = build_receipt(
        native_heartbeat=Path(args.native_heartbeat),
        github_sha=str(args.github_sha),
        github_run_id=str(args.github_run_id),
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    degraded = [
        name
        for name, row in receipt["venues"].items()
        if row["runtime_status"] != "HEALTHY"
    ]
    print(json.dumps({
        "output": str(target),
        "degraded_venues": degraded,
        "receipt_digest": receipt["receipt_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
