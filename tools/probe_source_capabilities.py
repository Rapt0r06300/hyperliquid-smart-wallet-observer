#!/usr/bin/env python3
"""Build current GitHub-hosted read-only source runtime evidence.

The receipt is deliberately conservative: network failure becomes DEGRADED,
never a fabricated HEALTHY state.  It never authenticates and never touches
trading endpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

VENUES = ("hyperliquid", "binance", "bybit", "okx", "gate", "bitget")
NATIVE_VENUES = ("bybit", "okx", "gate", "bitget")
BYBIT_TIME_URLS = (
    "https://api.bybit.com/v5/market/time",
    "https://api.bytick.com/v5/market/time",
)
RUNNER_IP_URLS = (
    "https://api64.ipify.org?format=json",
    "https://api.ipify.org?format=json",
)
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


def _exception_detail(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        body = ""
        try:
            body = exc.read(512).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        body = " ".join(body.split())[:240]
        return f"HTTP_{exc.code}" + (f":{body}" if body else "")
    return f"{type(exc).__name__}:{exc}"[:300]


def _probe_runner_network(request_json: Callable[..., object]) -> dict[str, object]:
    errors: list[str] = []
    for url in RUNNER_IP_URLS:
        try:
            payload = request_json(url, timeout=4.0)
            raw_ip = payload.get("ip") if isinstance(payload, dict) else None
            public_ip = str(raw_ip or "").strip()
            ipaddress.ip_address(public_ip)
        except Exception as exc:
            errors.append(f"{url}:{_exception_detail(exc)}")
            continue
        return {
            "status": "OBSERVED",
            "public_ip": public_ip,
            "source_url": url,
        }
    return {
        "status": "UNAVAILABLE",
        "public_ip": None,
        "source_url": None,
        "error": " | ".join(errors)[:1000],
    }


def _probe_bybit(request_json: Callable[..., object]) -> tuple[bool, str]:
    errors: list[str] = []
    for url in BYBIT_TIME_URLS:
        try:
            payload = request_json(url)
            if not isinstance(payload, dict) or int(payload.get("retCode", -1)) != 0:
                raise ValueError("BYBIT_TIME_INVALID")
            result = payload.get("result")
            valid_time = (
                isinstance(result, dict)
                and bool(result.get("timeSecond") or result.get("timeNano"))
            ) or bool(payload.get("time"))
            if not valid_time:
                raise ValueError("BYBIT_TIME_MISSING")
            host = url.split("/", 3)[2]
            return True, f"BYBIT_TIME_OK:{host}"
        except Exception as exc:
            errors.append(f"{url}:{_exception_detail(exc)}")
    return False, "BYBIT_UNAVAILABLE:" + " | ".join(errors)[:900]


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
        return False, f"BINANCE_UNAVAILABLE:{_exception_detail(exc)}"


def _load_json(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_native_heartbeat(path: Path) -> dict[str, object]:
    return _load_json(path)


def build_receipt(
    *,
    native_heartbeat: Path,
    github_sha: str,
    github_run_id: str,
    bbo_heartbeat: Path | None = None,
    request_json: Callable[..., object] = _request_json,
    now_utc: str | None = None,
) -> dict[str, object]:
    observed_at = now_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    hb = _load_native_heartbeat(native_heartbeat)
    bbo_hb = _load_json(bbo_heartbeat)
    last_event = hb.get("last_event_ms") if isinstance(hb.get("last_event_ms"), dict) else {}
    coordinator_health = (
        hb.get("coordinator_health")
        if isinstance(hb.get("coordinator_health"), dict)
        else {}
    )
    discovery_errors = (
        coordinator_health.get("discovery_errors")
        if isinstance(coordinator_health.get("discovery_errors"), dict)
        else {}
    )
    transport_errors = (
        coordinator_health.get("transport_errors")
        if isinstance(coordinator_health.get("transport_errors"), dict)
        else {}
    )

    runner_network = _probe_runner_network(request_json)
    hl_ok, hl_reason = _probe_hyperliquid(request_json)
    bin_rest_ok, bin_rest_reason = _probe_binance(request_json)
    bybit_rest_ok, bybit_rest_reason = _probe_bybit(request_json)

    venues: dict[str, object] = {}
    hl_runtime = "HEALTHY" if hl_ok else "DEGRADED"
    venues["hyperliquid"] = {
        "runtime_status": hl_runtime,
        "reason": hl_reason,
        "observed_at_utc": observed_at,
        "network_observed": hl_ok,
        "capability_runtime": {name: hl_runtime for name in CAPABILITIES},
    }

    bbo_expected = bbo_heartbeat is not None
    frames_bbo = int(bbo_hb.get("frames_bookticker") or 0)
    frames_trades = int(bbo_hb.get("frames_trades") or 0)
    frames_l2 = int(bbo_hb.get("binance_l2_publications") or 0)
    frames_l2_full = int(
        bbo_hb.get("binance_l2_full_publications")
        if bbo_hb.get("binance_l2_full_publications") is not None
        else frames_l2
    )
    frames_l2_partial = int(bbo_hb.get("binance_l2_partial_publications") or 0)
    bin_clock = (
        bbo_hb.get("binance_clock_sync")
        if isinstance(bbo_hb.get("binance_clock_sync"), dict)
        else {}
    )
    bin_ws_clock_ok = (
        isinstance(bin_clock.get("clock_offset_ms"), (int, float))
        and isinstance(bin_clock.get("clock_probe_rtt_ms"), (int, float))
        and float(bin_clock.get("clock_probe_rtt_ms")) >= 0.0
    )
    bin_ws_ok = frames_bbo > 0 and frames_trades > 0
    if bbo_expected:
        bin_ok = bin_ws_ok
        bin_reason = (
            (
                "BINANCE_WS_OBSERVED:"
                f"bbo={frames_bbo}:trades={frames_trades}:"
                f"l2_full={frames_l2_full}:l2_partial={frames_l2_partial}"
            )
            if bin_ws_ok
            else (
                "BINANCE_WS_NOT_OBSERVED:"
                f"bbo={frames_bbo}:trades={frames_trades}:"
                f"l2_full={frames_l2_full}:l2_partial={frames_l2_partial};"
                f"rest={bin_rest_reason}"
            )
        )
    else:
        bin_ok = bin_rest_ok
        bin_reason = bin_rest_reason
    bin_runtime = "HEALTHY" if bin_ok else "DEGRADED"
    bin_caps = {name: bin_runtime for name in CAPABILITIES}
    if bbo_expected:
        bin_caps["bbo"] = "HEALTHY" if frames_bbo > 0 else "DEGRADED"
        bin_caps["trades"] = "HEALTHY" if frames_trades > 0 else "DEGRADED"
        bin_caps["l2"] = "HEALTHY" if frames_l2_full > 0 else "DEGRADED"
        bin_caps["clock_sync"] = (
            "HEALTHY" if (bin_rest_ok or bin_ws_clock_ok) else "DEGRADED"
        )
    venues["binance"] = {
        "runtime_status": bin_runtime,
        "reason": bin_reason,
        "observed_at_utc": observed_at,
        "network_observed": bin_ok,
        "rest_probe_observed": bin_rest_ok,
        "rest_probe_reason": bin_rest_reason,
        "clock_sync_evidence": dict(bin_clock),
        "ws_frames": {
            "bbo": frames_bbo,
            "trades": frames_trades,
            "l2_publications": frames_l2,
            "l2_full_publications": frames_l2_full,
            "l2_partial_publications": frames_l2_partial,
        },
        "capability_runtime": bin_caps,
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
        if venue == "bybit" and not ok:
            details = [reason, f"REST={bybit_rest_reason}"]
            discovery_error = str(discovery_errors.get("bybit") or "")
            transport_error = str(transport_errors.get("bybit") or "")
            if discovery_error:
                details.append(f"DISCOVERY={discovery_error}")
            if transport_error:
                details.append(f"WS={transport_error}")
            reason = ";".join(details)[:1800]
        venue_caps = {name: runtime for name in CAPABILITIES}
        if venue == "bybit" and ok:
            venue_caps["clock_sync"] = "HEALTHY" if bybit_rest_ok else "DEGRADED"
        venues[venue] = {
            "runtime_status": runtime,
            "reason": reason,
            "observed_at_utc": observed_at,
            "network_observed": ok,
            "last_event_ms": event_ms,
            "capability_runtime": venue_caps,
        }
        if venue == "bybit":
            venues[venue]["rest_probe_observed"] = bybit_rest_ok
            venues[venue]["rest_probe_reason"] = bybit_rest_reason

    body: dict[str, object] = {
        "schema_version": "alina.source_capability_runtime.v1",
        "generated_at_utc": observed_at,
        "github_sha": github_sha,
        "github_run_id": github_run_id,
        "runner_kind": "github-hosted",
        "runner_network": runner_network,
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
    parser.add_argument("--bbo-heartbeat")
    parser.add_argument("--output", default="docs/source-capability-runtime.json")
    parser.add_argument("--github-sha", default=os.environ.get("GITHUB_SHA", "unknown"))
    parser.add_argument("--github-run-id", default=os.environ.get("GITHUB_RUN_ID", "unknown"))
    args = parser.parse_args()

    receipt = build_receipt(
        native_heartbeat=Path(args.native_heartbeat),
        bbo_heartbeat=Path(args.bbo_heartbeat) if args.bbo_heartbeat else None,
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
