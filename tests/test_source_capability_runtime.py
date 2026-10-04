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
    assert receipt["venues"]["bybit"]["runtime_status"] == "DEGRADED"
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
                "frames_l2_bin": 5,
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
    assert receipt["venues"]["binance"]["runtime_status"] == "DEGRADED"
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
                "frames_l2_bin": 0,
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

    assert receipt["venues"]["binance"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["binance"]["capability_runtime"]["l2"] == "DEGRADED"
    assert receipt["venues"]["binance"]["ws_frames"]["l2_partial_publications"] == 4
    assert receipt["venues"]["binance"]["ws_frames"]["l2_full_publications"] == 0

def test_bybit_live_ws_does_not_fake_clock_sync_when_rest_is_blocked(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 1,
                "last_event_ms": {
                    "bybit": 123,
                    "okx": 1,
                    "gate": 2,
                    "bitget": 3,
                },
                "coordinator_health": {
                    "clock_sync": {
                        "bybit": {
                            "status": "UNAVAILABLE",
                            "error": "WS public clock probe unavailable",
                        }
                    }
                },
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
            return {"serverTime": 123}
        if "api.bybit" in url or "api.bytick" in url:
            raise OSError("Bybit REST blocked")
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        github_sha="e" * 40,
        github_run_id="101",
        request_json=fake_request,
        now_utc="2026-10-03T00:00:00Z",
    )

    assert receipt["venues"]["bybit"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["bybit"]["capability_runtime"]["bbo"] == "DEGRADED"
    assert receipt["venues"]["bybit"]["capability_runtime"]["trades"] == "DEGRADED"
    assert receipt["venues"]["bybit"]["capability_runtime"]["clock_sync"] == "DEGRADED"
    assert receipt["venues"]["bybit"]["clock_sync_evidence"]["status"] == "UNAVAILABLE"
    assert "WS public clock probe unavailable" in receipt["venues"]["bybit"]["clock_sync_evidence"]["error"]

def test_runtime_receipt_accepts_binance_ws_clock_evidence(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 1,
                "last_event_ms": {
                    "bybit": 1,
                    "okx": 2,
                    "gate": 3,
                    "bitget": 4,
                },
            }
        ),
        encoding="utf-8",
    )
    bbo = tmp_path / "bbo.json"
    bbo.write_text(
        json.dumps(
            {
                "frames_bookticker": 4,
                "frames_trades": 5,
                "binance_l2_publications": 6,
                "binance_l2_full_publications": 6,
                "binance_l2_partial_publications": 0,
                "frames_l2_bin": 6,
                "binance_clock_sync": {
                    "clock_offset_ms": 1.5,
                    "clock_probe_rtt_ms": 12.0,
                    "clock_uncertainty_ms": 6.0,
                    "clock_probe_server_ts_ms": 1_000,
                    "clock_probe_receive_wall_ts_ms": 1_006,
                    "clock_probe_source": "websocket_api_depth_roundtrip",
                },
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
        if "api.bybit.com" in url or "api.bytick.com" in url:
            raise OSError("Bybit blocked")
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        bbo_heartbeat=bbo,
        github_sha="e" * 40,
        github_run_id="101",
        request_json=fake_request,
        now_utc="2026-10-03T00:00:00Z",
    )

    binance = receipt["venues"]["binance"]
    assert binance["runtime_status"] == "HEALTHY"
    assert binance["capability_runtime"]["l2"] == "HEALTHY"
    assert binance["capability_runtime"]["clock_sync"] == "HEALTHY"
    assert binance["clock_sync_evidence"]["clock_offset_ms"] == 1.5
    assert (
        binance["clock_sync_evidence"]["clock_probe_source"]
        == "websocket_api_depth_roundtrip"
    )

def test_full_publication_without_exploitable_book_stays_l2_degraded(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 1,
                "last_event_ms": {"bybit": 1, "okx": 2, "gate": 3, "bitget": 4},
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
                "binance_l2_publications": 3,
                "binance_l2_full_publications": 3,
                "binance_l2_partial_publications": 0,
                "frames_l2_bin": 0,
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
            raise OSError("Bybit REST blocked")
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        bbo_heartbeat=bbo,
        github_sha="f" * 40,
        github_run_id="102",
        request_json=fake_request,
        now_utc="2026-10-03T00:00:00Z",
    )

    assert receipt["venues"]["binance"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["binance"]["capability_runtime"]["l2"] == "DEGRADED"
    assert receipt["venues"]["binance"]["ws_frames"]["l2_full_publications"] == 3
    assert receipt["venues"]["binance"]["ws_frames"]["l2_exploitable_frames"] == 0

def test_runtime_receipt_preserves_binance_deep_l2_diagnostics(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 1,
                "last_event_ms": {"bybit": 1, "okx": 2, "gate": 3, "bitget": 4},
            }
        ),
        encoding="utf-8",
    )
    bbo = tmp_path / "bbo.json"
    bbo.write_text(
        json.dumps(
            {
                "frames_bookticker": 3,
                "frames_trades": 4,
                "frames_l2_bin": 0,
                "binance_l2_publications": 5,
                "binance_l2_full_publications": 0,
                "binance_l2_partial_publications": 5,
                "binance_deep_l2": {
                    "ws_api_snapshots_received": 0,
                    "ws_api_failures": 2,
                    "last_error": "REST=HTTP 451;WS_API=HTTP 451",
                },
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
        github_sha="a" * 40,
        github_run_id="103",
        request_json=fake_request,
        now_utc="2026-10-03T00:00:00Z",
    )

    deep = receipt["venues"]["binance"]["deep_l2_health"]
    assert deep["ws_api_failures"] == 2
    assert deep["last_error"] == "REST=HTTP 451;WS_API=HTTP 451"

def test_bybit_native_ws_clock_evidence_promotes_clock_sync(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 5,
                "last_event_ms": {
                    "bybit": 123,
                    "okx": 1,
                    "gate": 2,
                    "bitget": 3,
                },
                "coordinator_health": {
                    "clock_sync": {
                        "bybit": {
                            "status": "OK",
                            "source": "websocket_public_ping:stream.bybit.com:option",
                            "server_ts_ms": 1005,
                            "send_wall_ts_ms": 1000,
                            "receive_wall_ts_ms": 1010,
                            "rtt_ms": 10.0,
                            "offset_ms": 0.0,
                            "uncertainty_ms": 5.0,
                        }
                    }
                },
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
            return {"serverTime": 123}
        if "api.bybit" in url or "api.bytick" in url:
            raise OSError("Bybit REST blocked")
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        github_sha="f" * 40,
        github_run_id="104",
        request_json=fake_request,
        now_utc="2026-10-03T00:00:00Z",
    )

    bybit = receipt["venues"]["bybit"]
    assert bybit["runtime_status"] == "DEGRADED"
    assert bybit["capability_runtime"]["clock_sync"] == "HEALTHY"
    assert bybit["clock_sync_evidence"]["source"] == "websocket_public_ping:stream.bybit.com:option"
    assert bybit["clock_sync_evidence"]["rtt_ms"] == 10.0

def test_bybit_channel_counts_are_fail_closed(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 10,
                "last_event_ms": {
                    "bybit": 123,
                    "okx": 1,
                    "gate": 2,
                    "bitget": 3,
                },
                "channel_counts": {
                    "bybit": {
                        "bbo": 4,
                        "l2Book": 7,
                        "trades": 0,
                        "ticker": 5,
                    }
                },
                "coordinator_health": {
                    "clock_sync": {
                        "bybit": {
                            "status": "OK",
                            "source": "websocket_public_ping:stream.bybit.com:option",
                            "server_ts_ms": 1005,
                            "send_wall_ts_ms": 1000,
                            "receive_wall_ts_ms": 1010,
                            "rtt_ms": 10.0,
                            "offset_ms": 0.0,
                            "uncertainty_ms": 5.0,
                        }
                    }
                },
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
            return {"serverTime": 123}
        if "api.bybit" in url or "api.bytick" in url:
            raise OSError("Bybit REST blocked")
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        github_sha="1" * 40,
        github_run_id="105",
        request_json=fake_request,
        now_utc="2026-10-04T00:00:00Z",
    )

    bybit = receipt["venues"]["bybit"]
    assert bybit["runtime_status"] == "DEGRADED"
    assert bybit["capability_runtime"]["bbo"] == "HEALTHY"
    assert bybit["capability_runtime"]["l2"] == "HEALTHY"
    assert bybit["capability_runtime"]["trades"] == "DEGRADED"
    assert bybit["capability_runtime"]["clock_sync"] == "HEALTHY"
    assert bybit["capability_runtime"]["venue_status"] == "DEGRADED"
    assert bybit["channel_counts"]["bbo"] == 4
    assert bybit["channel_counts"]["l2Book"] == 7
    assert bybit["channel_counts"]["trades"] == 0
    assert "channels=bbo:4,l2:7,trades:0" in bybit["reason"]

def test_native_channel_counts_fail_closed_for_every_native_venue(tmp_path: Path) -> None:
    module = _module()
    native = tmp_path / "native.json"
    native.write_text(
        json.dumps(
            {
                "records_written": 20,
                "last_event_ms": {
                    "bybit": 1,
                    "okx": 2,
                    "gate": 3,
                    "bitget": 4,
                },
                "channel_counts": {
                    "bybit": {"bbo": 1, "l2Book": 1, "trades": 1},
                    "okx": {"bbo": 1, "l2Book": 1, "trades": 0},
                    "gate": {"bbo": 1, "l2Book": 0, "trades": 1},
                    "bitget": {"bbo": 0, "l2Book": 1, "trades": 1},
                },
                "coordinator_health": {
                    "clock_sync": {
                        venue: {
                            "status": "OK",
                            "offset_ms": 0.0,
                            "rtt_ms": 1.0,
                        }
                        for venue in ("bybit", "okx", "gate", "bitget")
                    }
                },
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
            return {"serverTime": 123}
        if "api.bybit" in url or "api.bytick" in url:
            raise OSError("Bybit REST blocked")
        raise AssertionError(url)

    receipt = module.build_receipt(
        native_heartbeat=native,
        github_sha="2" * 40,
        github_run_id="106",
        request_json=fake_request,
        now_utc="2026-10-04T00:00:00Z",
    )

    assert receipt["venues"]["bybit"]["runtime_status"] == "HEALTHY"
    assert receipt["venues"]["okx"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["gate"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["bitget"]["runtime_status"] == "DEGRADED"
    assert receipt["venues"]["bybit"]["capability_runtime"]["trades"] == "HEALTHY"
    assert receipt["venues"]["okx"]["capability_runtime"]["trades"] == "DEGRADED"
    assert receipt["venues"]["gate"]["capability_runtime"]["l2"] == "DEGRADED"
    assert receipt["venues"]["bitget"]["capability_runtime"]["bbo"] == "DEGRADED"
    assert receipt["venues"]["bitget"]["capability_runtime"]["l2"] == "HEALTHY"

