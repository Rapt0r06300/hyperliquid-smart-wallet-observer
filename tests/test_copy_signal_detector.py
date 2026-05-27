from hl_observer.config.loader import load_settings
from hl_observer.copying.signal_detector import CopySignalTuning, detect_copy_signals_from_deltas, signal_type_from_delta
from hl_observer.hyperliquid.schemas import SignalDecision
from hl_observer.storage.models import PositionDeltaModel, TopWallet


def _settings():
    settings = load_settings()
    settings.risk.max_signal_age_ms = 10_000
    settings.risk.min_signal_score = 75
    settings.risk.min_wallet_score = 70
    settings.risk.min_edge_required_bps = 8
    return settings


def _delta(delta_type: str, *, wallet: str = "0x" + "1" * 40, detected_at_ms: int = 1_000) -> PositionDeltaModel:
    is_short = "short" in delta_type.lower()
    return PositionDeltaModel(
        wallet_address=wallet,
        coin="BTC",
        previous_side=None if "open" in delta_type.lower() else ("short" if is_short else "long"),
        new_side="short" if is_short else "long",
        previous_size=0.0 if "open" in delta_type.lower() else 1.0,
        current_size=-1.0 if is_short else 1.0,
        new_size=-1.0 if is_short else 1.0,
        delta_size=1.0,
        delta_notional_usdc=50_000.0,
        action=delta_type.upper(),
        exchange_ts=detected_at_ms,
        side="short" if is_short else "long",
        price=50_000.0,
        fill_size=1.0,
        delta_type=delta_type,
        confidence_score=0.95,
        detected_at_ms=detected_at_ms,
        delta_hash=delta_type,
    )


def _leader(address: str = "0x" + "1" * 40) -> TopWallet:
    return TopWallet(wallet_address=address, rank=1, source="leaderboard", score=88.0, selected_at_ms=1_000, status="selected")


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
        tuning=CopySignalTuning(edge_leader_bps=70.0),
    )

    assert report.dry_run is True
    assert report.signals_created == 1
    assert report.signals[0].signal_type == "open"
    assert report.signals[0].side == "long"
    assert report.signals[0].edge_remaining_bps > 0
    assert report.signals[0].decision in {SignalDecision.PAPER_TRADE, SignalDecision.PAPER_CANDIDATE}


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
        tuning=CopySignalTuning(edge_leader_bps=5.0),
    )

    assert report.signals_created == 1
    assert report.signals[0].edge_remaining_bps <= 0
    assert report.signals[0].decision == SignalDecision.REJECT_EDGE_NEGATIVE
    assert report.no_trade_reasons["edge_remaining_bps_non_positive"] == 1


def test_copy_signal_detector_ignores_unfollowed_wallet():
    report = detect_copy_signals_from_deltas(
        [_delta("open_long", wallet="0x" + "2" * 40)],
        settings=_settings(),
        followed_wallets=[_leader()],
        now_timestamp_ms=1_000,
    )

    assert report.signals_created == 0
    assert report.no_trade_reasons["wallet_not_followed"] == 1
