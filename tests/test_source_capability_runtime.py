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
