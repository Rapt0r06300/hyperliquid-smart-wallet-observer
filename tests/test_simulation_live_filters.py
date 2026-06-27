from __future__ import annotations

from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig
from hl_observer.simulation.live_filters import (
    DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS,
    DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS,
    DEFAULT_SIMULATION_MIN_EDGE_BPS,
    DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE,
    DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS,
    copy_candidate_signal_time_ms,
    delta_identity,
    hard_stale_signal_limit_ms,
)
from hl_observer.storage.models import PositionDeltaModel


def _delta(**overrides) -> PositionDeltaModel:
    data = {
        "wallet_address": "0x" + "1" * 40,
        "coin": "ETH",
        "previous_side": "FLAT",
        "new_side": "LONG",
        "previous_size": 0.0,
        "current_size": 1.0,
        "new_size": 1.0,
        "delta_size": 1.0,
        "delta_notional_usdc": 2_000.0,
        "action": "OPEN",
        "exchange_ts": 1_000,
        "detected_at_ms": 9_000,
        "source": "hyperliquid_rest:userFillsByTime",
        "side": "B",
        "price": 2_000.0,
        "fill_size": 1.0,
        "delta_type": "open_long",
        "confidence_score": 0.95,
        "raw_json": {},
    }
    data.update(overrides)
    return PositionDeltaModel(**data)


def test_realtime_copy_config_defaults_match_v9_calibration():
    cfg = RealtimeCopyRiskConfig()

    assert cfg.min_edge_required_bps == DEFAULT_SIMULATION_MIN_EDGE_BPS
    assert cfg.max_signal_age_ms == DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS
    assert cfg.min_liquidity_score == DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE
    assert cfg.max_copy_degradation_bps == DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS
    assert cfg.single_wallet_min_edge_required_bps == DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS
    assert hard_stale_signal_limit_ms(cfg.max_signal_age_ms) == 30_000


def test_rest_backfill_uses_fill_timestamp_not_detection_timestamp():
    row = _delta(raw_json={"time": 1_000, "hash": "0xabc"})

    assert copy_candidate_signal_time_ms(row) == 1_000


def test_live_ws_delta_uses_detection_timestamp_for_freshness():
    row = _delta(source="hyperliquid_ws:userFills", raw_json={"time": 1_000, "hash": "0xabc"})

    assert copy_candidate_signal_time_ms(row) == 9_000


def test_fresh_opportunity_cluster_uses_latest_cluster_signal_timestamp():
    row = _delta(
        source="fresh_opportunity_cluster_local_simulation",
        detected_at_ms=6_000,
        raw_json={"leader_signal_ts": 12_000, "time": 1_000},
    )

    assert copy_candidate_signal_time_ms(row) == 12_000


def test_delta_identity_dedupes_same_fill_across_poll_rows():
    first = _delta(id=1, delta_hash="first", raw_json={"hash": "0xabc", "tid": 7, "oid": 9, "time": 1_000})
    second = _delta(id=2, delta_hash="second", raw_json={"hash": "0xabc", "tid": 7, "oid": 9, "time": 1_000})

    assert delta_identity(first) == delta_identity(second)
    assert delta_identity(first).startswith("fill:")
