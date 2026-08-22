from __future__ import annotations

import json
from pathlib import Path

import pytest

import hl_observer.runtime.lead_lag_event_runtime as runtime_module
from hl_observer.backtesting.lead_lag_evidence import (
    REQUIRED_CRITERIA,
    SCHEMA_VERSION,
    estimate_alpha_half_life_ms,
)
from hl_observer.runtime.lead_lag_event_runtime import LeadLagEventPaperRuntime
from tools.collecter_bbo import dispatch_lead_lag_trade


def _write_promoted_config(
    root: Path,
    *,
    half_life_ms: float = 500.0,
    runtime_latency_ms: float = 20.0,
    safety_margin_ms: float = 20.0,
) -> Path:
    path = root / "runtime" / "data" / "lead_lag_config_gele.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "strategy": "lead_lag_shadow",
                "promotion_status": "PROMOTED",
                "dataset_hash": "sha256:" + "1" * 64,
                "pipeline_hash": "sha256:" + "2" * 64,
                "freeze_ts": "2026-07-29T00:00:00+00:00",
                "freeze_ts_ms": 1,
                "coins": ["ETH"],
                "control_coins": [],
                "requested_horizons_ms": [100.0],
                "observable_horizons_ms": [100.0],
                "minimum_events": 30,
                "seuil_choc_bps": 8.0,
                "edge_net_par_horizon_bps": {"100": 80.0},
                "sample_n_by_horizon": {"100": 40},
                "costs": {"round_trip_bps": 6.0, "executable": True},
                "latency_budget": {
                    "alpha_half_life_p95_ms": half_life_ms,
                    "end_to_end_latency_p95_ms": runtime_latency_ms,
                    "safety_margin_ms": safety_margin_ms,
                },
                "frequency": {"events_per_day": 5.0},
                "criteria": {name: True for name in REQUIRED_CRITERIA},
                "global_trials": {"count": 1},
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _trade(event_id: str, *, price: float, received_ms: int) -> dict:
    return {
        "event_id": event_id,
        "coin": "ETH",
        "px": price,
        "recv_wall_ts_ms": received_ms,
        "ts_wall_ms": received_ms,
    }


def _trade_with_monotonic(
    event_id: str,
    *,
    price: float,
    received_ms: int,
    received_monotonic_ns: int,
) -> dict:
    event = _trade(event_id, price=price, received_ms=received_ms)
    event["recu_ns"] = received_monotonic_ns
    return event


def _quote(*, received_ms: int) -> dict:
    return {
        "coin": "ETH",
        "bid": 100.0,
        "ask": 100.01,
        "bid_sz": 100.0,
        "ask_sz": 100.0,
        "recv_wall_ts_ms": received_ms,
        "ts_ex": received_ms - 1,
    }


def test_half_life_is_interpolated_only_inside_observed_horizons() -> None:
    assert estimate_alpha_half_life_ms({50.0: 40.0, 100.0: 30.0, 250.0: 15.0}) == pytest.approx(
        200.0
    )
    assert estimate_alpha_half_life_ms({50.0: 40.0, 100.0: 35.0}) is None


def test_trade_event_calls_canonical_paper_engine_inline(tmp_path: Path) -> None:
    _write_promoted_config(tmp_path)
    runtime = LeadLagEventPaperRuntime(tmp_path)
    assert runtime.enabled
    assert runtime.real_execution is False

    baseline = runtime.on_trade(
        _trade("trade-1", price=100.0, received_ms=1_000_000),
        None,
        now_ms=1_000_000,
    )
    assert baseline.code == "BASELINE_INITIALIZED"

    outcome = runtime.on_trade(
        _trade("trade-2", price=100.20, received_ms=1_000_010),
        _quote(received_ms=1_000_009),
        now_ms=1_000_015,
    )
    assert outcome.accepted is True
    assert outcome.code == "PAPER_ACCEPTED"
    assert outcome.paper_result is not None
    assert outcome.paper_result.ledger_snapshot
    assert len(runtime.paper_engine.positions) == 1


def test_event_is_rejected_when_runtime_latency_consumes_half_life(tmp_path: Path) -> None:
    _write_promoted_config(tmp_path, half_life_ms=100.0, safety_margin_ms=20.0)
    runtime = LeadLagEventPaperRuntime(tmp_path)
    runtime.on_trade(
        _trade("trade-1", price=100.0, received_ms=1_000_000),
        None,
        now_ms=1_000_000,
    )
    outcome = runtime.on_trade(
        _trade("trade-2", price=100.20, received_ms=1_000_010),
        _quote(received_ms=1_000_009),
        now_ms=1_000_095,
    )
    assert outcome.accepted is False
    assert outcome.code == "ALPHA_HALF_LIFE_EXPIRED"
    assert not runtime.paper_engine.positions


def test_monotonic_dispatch_latency_overrides_wall_clock_skew(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_promoted_config(tmp_path, half_life_ms=100.0, safety_margin_ms=20.0)
    clock = iter((1_005_000_000, 2_005_000_000))
    monkeypatch.setattr(runtime_module.time, "monotonic_ns", lambda: next(clock))
    runtime = LeadLagEventPaperRuntime(tmp_path)
    runtime.on_trade(
        _trade_with_monotonic(
            "trade-1",
            price=100.0,
            received_ms=1_000_000,
            received_monotonic_ns=1_000_000_000,
        ),
        None,
        now_ms=1_000_000,
    )
    outcome = runtime.on_trade(
        _trade_with_monotonic(
            "trade-2",
            price=100.20,
            received_ms=1_000_010,
            received_monotonic_ns=2_000_000_000,
        ),
        _quote(received_ms=1_000_009),
        now_ms=1_000_095,
    )

    assert outcome.accepted is True
    assert outcome.latency_ms == pytest.approx(5.0)
    rows = [
        json.loads(line)
        for line in runtime.decisions_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["latency_kind"] == "LOCAL_MONOTONIC_DISPATCH"


def test_monotonic_latency_sampling_is_globally_throttled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_promoted_config(tmp_path)
    clock = iter((1_005_000_000, 1_005_500_000, 2_100_000_000))
    monkeypatch.setattr(runtime_module.time, "monotonic_ns", lambda: next(clock))
    runtime = LeadLagEventPaperRuntime(tmp_path, latency_sample_interval_ms=1_000)
    events = (
        _trade_with_monotonic(
            "trade-1", price=100.0, received_ms=1_000_000,
            received_monotonic_ns=1_000_000_000,
        ),
        _trade_with_monotonic(
            "trade-2", price=100.001, received_ms=1_000_001,
            received_monotonic_ns=1_005_100_000,
        ),
        _trade_with_monotonic(
            "trade-3", price=100.002, received_ms=1_001_100,
            received_monotonic_ns=2_095_000_000,
        ),
    )
    for event in events:
        runtime.on_trade(event, None, now_ms=int(event["recv_wall_ts_ms"]))

    rows = [
        json.loads(line)
        for line in runtime.decisions_path.read_text(encoding="utf-8").splitlines()
    ]
    samples = [row for row in rows if row.get("sample_only") is True]
    assert len(samples) == 2
    assert all(row["latency_kind"] == "LOCAL_MONOTONIC_DISPATCH" for row in samples)


def test_rejected_frozen_evidence_keeps_runtime_disabled(tmp_path: Path) -> None:
    config_path = _write_promoted_config(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["promotion_status"] = "REJECTED"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    runtime = LeadLagEventPaperRuntime(tmp_path)
    outcome = runtime.on_trade(
        _trade("trade-1", price=100.0, received_ms=1_000_000),
        None,
        now_ms=1_000_000,
    )
    assert runtime.enabled is False
    assert outcome.code == "EVIDENCE_NOT_PROMOTED"
    assert not runtime.paper_engine.positions


def test_event_id_is_deduplicated(tmp_path: Path) -> None:
    _write_promoted_config(tmp_path)
    runtime = LeadLagEventPaperRuntime(tmp_path)
    event = _trade("same-event", price=100.0, received_ms=1_000_000)
    assert runtime.on_trade(event, None, now_ms=1_000_000).code == "BASELINE_INITIALIZED"
    assert runtime.on_trade(event, None, now_ms=1_000_000).code == "DUPLICATE_EVENT"


def test_collector_dispatch_is_synchronous_and_failure_isolated() -> None:
    calls: list[tuple[dict, dict | None, int]] = []

    class Runtime:
        def on_trade(self, trade, quote, *, now_ms):
            calls.append((trade, quote, now_ms))
            return "ok"

    trade = _trade("trade-1", price=100.0, received_ms=1_000_000)
    quote = _quote(received_ms=999_999)
    assert dispatch_lead_lag_trade(Runtime(), trade, quote, now_ms=1_000_000) == "ok"
    assert calls == [(trade, quote, 1_000_000)]


def test_collector_has_no_periodic_lead_lag_worker() -> None:
    source = Path("tools/collecter_bbo.py").read_text(encoding="utf-8")
    binance_body = source.split("async def binance_ag():", 1)[1].split(
        "async def ecrire_et_superviser():", 1
    )[0]
    assert "dispatch_lead_lag_trade(" in binance_body
    assert "await asyncio.sleep(60" not in binance_body
