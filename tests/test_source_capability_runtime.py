from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path("tools/probe_source_capabilities.py")
    spec = importlib.util.spec_from_file_location("probe_source_capabilities", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_receipt_is_fail_closed_and_paper_only(tmp_path: Path) -> None:
    module = _module()
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(
        json.dumps(
            {
                "records_written": 12,
                "last_event_ms": {
                    "bybit": 100,
                    "okx": 101,
                    "gate": 102,
                    "bitget": 0,
                },
                "read_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )

    def fake_request(url: str, **kwargs):
        if "hyperliquid" in url:
            return {"universe": [{"name": "BTC"}]}
        if "binance" in url:
            return {"serverTime": 123}
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=heartbeat,
        github_sha="a" * 40,
        github_run_id="42",
        request_json=fake_request,
        now_utc="2026-09-30T00:00:00Z",
    )

    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False
    assert receipt["runner_kind"] == "github-hosted"
    assert receipt["venues"]["hyperliquid"]["runtime_status"] == "HEALTHY"
    assert receipt["venues"]["binance"]["runtime_status"] == "HEALTHY"
    assert receipt["venues"]["bybit"]["runtime_status"] == "HEALTHY"
    assert receipt["venues"]["bitget"]["runtime_status"] == "DEGRADED"
    assert len(receipt["receipt_digest"]) == 64


def test_runtime_receipt_keeps_http_failure_degraded(tmp_path: Path) -> None:
    module = _module()
    heartbeat = tmp_path / "missing.json"

    def failing_request(*args, **kwargs):
        raise OSError("offline")

    receipt = module.build_receipt(
        native_heartbeat=heartbeat,
        github_sha="b" * 40,
        github_run_id="7",
        request_json=failing_request,
        now_utc="2026-09-30T00:00:00Z",
    )

    assert receipt["venues"]["hyperliquid"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["binance"]["runtime_status"] == "DEGRADED"
    assert all(
        receipt["venues"][venue]["runtime_status"] == "DEGRADED"
        for venue in ("bybit", "okx", "gate", "bitget")
    )


def test_runtime_receipt_records_runner_ip_and_uses_real_binance_ws_evidence(
    tmp_path: Path,
) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 5,
                "last_event_ms": {
                    "bybit": 0,
                    "okx": 1,
                    "gate": 2,
                    "bitget": 3,
                },
                "coordinator_health": {
                    "discovery_errors": {
                        "bybit": "RuntimeError: primary endpoint blocked",
                    },
                    "transport_errors": {},
                },
            }
        ),
        encoding="utf-8",
    )
    bbo = tmp_path / "bbo.json"
    bbo.write_text(
        json.dumps(
            {
                "frames_bookticker": 12,
                "frames_trades": 34,
                "binance_l2_publications": 5,
            }
        ),
        encoding="utf-8",
    )

    def fake_request(url: str, **kwargs):
        if "ipify" in url:
            return {"ip": "20.42.1.2"}
        if "hyperliquid" in url:
            return {"universe": [{"name": "BTC"}]}
        if "fapi.binance.com" in url:
            raise OSError("REST blocked")
        if "api.bybit.com" in url:
            raise OSError("primary blocked")
        if "api.bytick.com" in url:
            return {
                "retCode": 0,
                "result": {"timeSecond": "1790000000"},
            }
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        bbo_heartbeat=bbo,
        github_sha="c" * 40,
        github_run_id="99",
        request_json=fake_request,
        now_utc="2026-10-03T00:00:00Z",
    )

    assert receipt["runner_network"]["public_ip"] == "20.42.1.2"
    assert receipt["venues"]["binance"]["runtime_status"] == "HEALTHY"
    assert receipt["venues"]["binance"]["ws_frames"]["bbo"] == 12
    assert receipt["venues"]["binance"]["capability_runtime"]["l2"] == "HEALTHY"
    assert receipt["venues"]["binance"]["capability_runtime"]["clock_sync"] == "DEGRADED"
    assert receipt["venues"]["bybit"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["bybit"]["rest_probe_observed"] is True
    assert "api.bytick.com" in receipt["venues"]["bybit"]["rest_probe_reason"]

def test_runtime_receipt_does_not_promote_partial_binance_l2_to_full(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 1,
                "last_event_ms": {
                    "bybit": 0,
                    "okx": 1,
                    "gate": 2,
                    "bitget": 3,
                },
            }
        ),
        encoding="utf-8",
    )
    bbo = tmp_path / "bbo.json"
    bbo.write_text(
        json.dumps(
            {
                "frames_bookticker": 10,
                "frames_trades": 10,
                "binance_l2_publications": 4,
                "binance_l2_full_publications": 0,
                "binance_l2_partial_publications": 4,
            }
        ),
        encoding="utf-8",
    )

    def fake_request(url: str, **kwargs):
        if "ipify" in url:
            return {"ip": "20.42.1.2"}
        if "hyperliquid" in url:
            return {"universe": [{"name": "BTC"}]}
        if "fapi.binance.com" in url:
            raise OSError("REST blocked")
        if "api.bybit" in url or "api.bytick" in url:
            raise OSError("Bybit blocked")
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        bbo_heartbeat=bbo,
        github_sha="d" * 40,
        github_run_id="100",
        request_json=fake_request,
        now_utc="2026-10-03T00:00:00Z",
    )

    assert receipt["venues"]["binance"]["runtime_status"] == "HEALTHY"
    assert receipt["venues"]["binance"]["capability_runtime"]["l2"] == "DEGRADED"
    assert receipt["venues"]["binance"]["ws_frames"]["l2_partial_publications"] == 4
    assert receipt["venues"]["binance"]["ws_frames"]["l2_full_publications"] == 0

