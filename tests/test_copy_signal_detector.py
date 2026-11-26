from hl_observer.config.loader import load_settings
from hl_observer.copying.signal_detector import (
    CopySignalTuning,
    detect_copy_signals_from_deltas,
    signal_type_from_delta,
)
from hl_observer.hyperliquid.schemas import SignalDecision
from hl_observer.storage.models import PositionDeltaModel, TopWallet


def _settings():
    settings = load_settings()
    settings.risk.max_signal_age_ms = 10_000
    settings.risk.min_signal_score = 75
    settings.risk.min_wallet_score = 70
    settings.risk.min_edge_required_bps = 8
    return settings


def _delta(
    delta_type: str,
    *,
    wallet: str = "0x" + "1" * 40,
    detected_at_ms: int = 1_000,
    **overrides,
) -> PositionDeltaModel:
    is_short = "short" in delta_type.lower()
    data = {
        "wallet_address": wallet,
        "coin": "BTC",
        "previous_side": None if "open" in delta_type.lower() else ("short" if is_short else "long"),
        "new_side": "short" if is_short else "long",
        "previous_size": 0.0 if "open" in delta_type.lower() else 1.0,
        "current_size": -1.0 if is_short else 1.0,
        "new_size": -1.0 if is_short else 1.0,
        "delta_size": 1.0,
        "delta_notional_usdc": 50_000.0,
        "action": delta_type.upper(),
        "exchange_ts": detected_at_ms,
        "side": "short" if is_short else "long",
        "price": 50_000.0,
        "fill_size": 1.0,
        "delta_type": delta_type,
        "confidence_score": 0.95,
        "detected_at_ms": detected_at_ms,
        "delta_hash": delta_type,
    }
    data.update(overrides)
    return PositionDeltaModel(**data)


def _leader(address: str = "0x" + "1" * 40) -> TopWallet:
    return TopWallet(wallet_address=address, rank=1, source="leaderboard", score=88.0, selected_at_ms=1_000, status="selected")


def _test_tuning(expected_move_bps: float) -> CopySignalTuning:
    # Synthetic, explicit depth used only to exercise the detector's mechanics.
    return CopySignalTuning(
        leader_expected_move_bps=expected_move_bps,
        # Explicit zero is a test fixture only; production must provide a
        # funding estimate derived from admissible prior observations.
        funding_expected_cost_bps=0.0,
        orderbook_depth_usdc=25_000.0,
    )


def test_delta_detector_supports_open_and_add_only_for_copy_entries():
    assert signal_type_from_delta(_delta("open_long")) == "open"
    assert signal_type_from_delta(_delta("open_short")) == "open"
    assert signal_type_from_delta(_delta("add_long")) == "add"
    assert signal_type_from_delta(_delta("reduce_long")) is None
    assert signal_type_from_delta(_delta("close_short")) is None


def test_copy_signal_detector_creates_paper_candidate_from_open_long():
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
        tuning=_test_tuning(70.0),
    )

    assert report.dry_run is True
    assert report.signals_created == 1
    assert report.signals[0].signal_type == "open"
    assert report.signals[0].side == "long"
    assert report.signals[0].edge_remaining_bps > 0
    assert report.signals[0].decision in {SignalDecision.PAPER_TRADE, SignalDecision.PAPER_CANDIDATE}


def test_copy_signal_detector_does_not_invent_expected_move_by_default():
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
    )

    assert CopySignalTuning().leader_expected_move_bps == 0.0
    assert report.signals_created == 0
    assert report.paper_candidates == 0
    assert report.no_trade_reasons["leader_expected_move_unmeasured"] == 1


def test_copy_signal_detector_requires_observed_depth_instead_of_static_default():
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
        tuning=CopySignalTuning(leader_expected_move_bps=70.0),
    )

    assert report.signals_created == 0
    assert report.paper_candidates == 0
    assert report.no_trade_reasons["orderbook_depth_unmeasured"] == 1


def test_copy_signal_detector_refuses_when_funding_cost_is_unmeasured():
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
        tuning=CopySignalTuning(
            leader_expected_move_bps=70.0,
            orderbook_depth_usdc=25_000.0,
        ),
    )

    assert report.signals_created == 0
    assert report.paper_candidates == 0
    assert report.no_trade_reasons["funding_cost_unmeasured"] == 1


def test_copy_signal_detector_refuses_non_finite_funding_cost():
    tuning = _test_tuning(70.0)
    tuning.funding_expected_cost_bps = float("nan")
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
        tuning=tuning,
    )

    assert report.signals_created == 0
    assert report.paper_candidates == 0
    assert report.no_trade_reasons["funding_cost_invalid"] == 1


def test_copy_signal_detector_refuses_negative_execution_cost_even_after_mutation():
    tuning = _test_tuning(70.0)
    tuning.estimated_slippage_bps = -1.0
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
        tuning=tuning,
    )

    assert report.signals_created == 0
    assert report.paper_candidates == 0
    assert report.no_trade_reasons["edge_cost_input_invalid"] == 1


def test_copy_signal_detector_rejects_reduce_close_as_no_trade():
    report = detect_copy_signals_from_deltas(
        [_delta("reduce_long"), _delta("close_short")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
    )

    assert report.signals_created == 0
    assert report.no_trade_reasons["leader_reduce_close_not_entry"] == 2


def test_copy_signal_detector_requires_positive_edge_remaining():
    report = detect_copy_signals_from_deltas(
        [_delta("open_short")],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
        tuning=_test_tuning(5.0),
    )

    assert report.signals_created == 1
    assert report.signals[0].edge_remaining_bps <= 0
    assert report.signals[0].decision == SignalDecision.REJECT_EDGE_NEGATIVE
    assert report.no_trade_reasons["edge_remaining_bps_non_positive"] == 1


def test_copy_signal_detector_uses_v9_simulation_defaults_without_env(monkeypatch):
    settings = _settings()
    settings.risk.max_signal_age_ms = 3_000
    settings.risk.min_edge_required_bps = 25
    monkeypatch.delenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", raising=False)
    monkeypatch.delenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", raising=False)

    accepted_with_v9_defaults = detect_copy_signals_from_deltas(
        [_delta("open_long", detected_at_ms=1_000)],
        settings=settings,
        followed_wallets=[_leader()],
        now_timestamp_ms=11_000,
        tuning=_test_tuning(31.0),
    )

    # Frais taker lus à la source unique (4,5 bps, et non plus 4,0 recopiés) :
    # Cycle complet : 31 − 2×4,5 − 3 − 2×5 − 2 − 2 = 5 bps.
    assert round(accepted_with_v9_defaults.signals[0].edge_remaining_bps, 6) == 5.0
    # Durcissement délibéré (snapshot 5e49646): DEFAULT_SIMULATION_MIN_EDGE_BPS
    # relevé à 28 (plancher effectif = min(settings=25, 28) = 25 bps sans env).
    # Un edge net de 5 bps est donc CORRECTEMENT refusé.
    assert (
        accepted_with_v9_defaults.signals[0].decision
        == SignalDecision.REJECT_EDGE_TOO_SMALL
    )


def test_copy_signal_detector_uses_live_simulation_age_window_override(monkeypatch):
    settings = _settings()
    settings.risk.max_signal_age_ms = 3_000
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "20000")
    accepted_with_override = detect_copy_signals_from_deltas(
        [_delta("open_long", detected_at_ms=1_000)],
        settings=settings,
        followed_wallets=[_leader()],
        now_timestamp_ms=11_000,
        tuning=_test_tuning(70.0),
    )

    assert accepted_with_override.signals[0].decision in {
        SignalDecision.PAPER_TRADE,
        SignalDecision.PAPER_CANDIDATE,
    }


def test_copy_signal_detector_uses_live_ws_detection_time_for_freshness(monkeypatch):
    settings = _settings()
    settings.risk.max_signal_age_ms = 3_000
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "15000")

    report = detect_copy_signals_from_deltas(
        [
            _delta(
                "open_short",
                detected_at_ms=20_000,
                # The exchange fill timestamp can be older than the live receipt.
                # WebSocket userFills source must be judged by local detection time.
                exchange_ts=1_000,
                source="hyperliquid_ws:userFills:stream",
                raw_json={"time": 1_000, "hash": "0xlive"},
            )
        ],
        settings=settings,
        followed_wallets=[_leader()],
        now_timestamp_ms=21_000,
        tuning=_test_tuning(70.0),
    )

    assert report.signals[0].timestamp_ms == 20_000
    assert report.signals[0].signal_age_ms == 1_000
    assert report.signals[0].decision in {
        SignalDecision.PAPER_TRADE,
        SignalDecision.PAPER_CANDIDATE,
    }
    assert "REJECT_TOO_LATE" not in report.no_trade_reasons


def test_copy_signal_detector_ignores_unfollowed_wallet():
    report = detect_copy_signals_from_deltas(
        [_delta("open_long", wallet="0x" + "2" * 40)],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
    )

    assert report.signals_created == 0
    assert report.no_trade_reasons["wallet_not_followed"] == 1


def test_copy_signal_detector_fails_closed_when_followed_list_is_empty():
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[],
        now_timestamp_ms=1_000,
        tuning=CopySignalTuning(leader_expected_move_bps=70.0),
    )

    assert report.signals_created == 0
    assert report.paper_candidates == 0
    assert report.no_trade_reasons["wallet_not_followed"] == 1


def test_copy_signal_detector_fails_closed_when_all_followed_wallets_are_rejected():
    rejected = _leader()
    rejected.status = "rejected"
    report = detect_copy_signals_from_deltas(
        [_delta("open_long")],
        settings=_settings(),
        followed_wallets=[rejected],
        now_timestamp_ms=1_000,
        tuning=CopySignalTuning(leader_expected_move_bps=70.0),
    )

    assert report.signals_created == 0
    assert report.paper_candidates == 0
    assert report.no_trade_reasons["wallet_not_followed"] == 1
