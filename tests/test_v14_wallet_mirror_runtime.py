from hl_observer.copy_mode.wallet_mirror_runtime import (
    MirrorRuntimeConfig,
    candidate_to_paper_intent,
    mirror_candidate_from_delta,
)
from hl_observer.paper_trading.mirror_paper_executor import execute_mirror_candidate_paper
from hl_observer.paper_trading.paper_connector import PaperSimConnector
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.risk.proportional_paper_sizer import ProportionalSizingConfig, size_proportional_paper_notional
from hl_observer.risk.slippage_guard_v2 import SlippageGuardConfig, evaluate_slippage_guard_v2
from hl_observer.signals.copy_conflict_resolver import resolve_copy_conflicts
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.strategies.models import IntentAction
from hl_observer.watchlists.smart_money_watchlist import build_smart_money_watchlist


def _delta(
    *,
    wallet: str = "0x" + "a" * 40,
    coin: str = "HYPE",
    action: LifecycleAction = LifecycleAction.OPEN_LONG,
    prev: float = 0.0,
    cur: float = 10.0,
    time_ms: int = 1_000,
    evidence: str = "fill:leader:1",
) -> LeaderDelta:
    return LeaderDelta(
        delta_id="ld_fixture_" + action.value + "_" + wallet[-4:],
        wallet=wallet,
        coin=coin,
        action=action,
        previous_size=prev,
        current_size=cur,
        delta_size=cur - prev,
        observed_at_ms=time_ms + 100,
        leader_event_time_ms=time_ms,
        source="test",
        confidence=0.92,
        reason_codes=(),
        evidence_ref=evidence,
    )


def test_mirror_detects_leader_open():
    candidate = mirror_candidate_from_delta(
        _delta(),
        leader_price=25.0,
        observed_time_ms=1_500,
        wallet_score=0.8,
        copyability_score=0.75,
        config=MirrorRuntimeConfig(max_signal_age_ms=2_000),
    )

    assert candidate.is_entry is True
    assert candidate.side == "LONG"
    assert candidate.leader_size == 10.0
    assert candidate.reason_codes == ()
    assert candidate.paper_only is True
    assert "fill:leader:1" in candidate.source_fill_refs


def test_mirror_proportional_sizing_caps_notional():
    sizing = size_proportional_paper_notional(
        leader_size=100.0,
        leader_price=20.0,
        equity_usdt=1_000.0,
        config=ProportionalSizingConfig(copy_ratio=0.50, max_mirror_notional_usdt=75.0, max_equity_pct=5.0),
    )

    assert sizing.accepted is True
    assert sizing.leader_notional_usdt == 2_000.0
    assert sizing.paper_notional_usdt == 50.0
    assert sizing.capped_by_absolute_limit is True
    assert sizing.capped_by_equity is True


def test_mirror_slippage_guard_blocks_low_depth():
    decision = evaluate_slippage_guard_v2(
        side="BUY",
        notional_usdt=100.0,
        mid_price=25.0,
        asks=((25.5, 1.0),),
        bids=((24.9, 10.0),),
        config=SlippageGuardConfig(max_slippage_bps=10.0, min_fill_ratio=0.90),
    )

    assert decision.accepted is False
    assert decision.reason in {"MISSED_FILL", "DEPTH_SLIPPAGE_TOO_HIGH", "PARTIAL_FILL_BELOW_FULL_COPY_STANDARD"}
    assert decision.evidence["depth_result"]["fill_ratio"] < 1.0


def test_mirror_paper_trade_has_not_an_order_and_keeps_evidence():
    candidate = mirror_candidate_from_delta(
        _delta(),
        leader_price=25.0,
        observed_time_ms=1_100,
        wallet_score=0.85,
        copyability_score=0.80,
        config=MirrorRuntimeConfig(copy_ratio=0.05, max_signal_age_ms=2_000),
    )
    connector = PaperSimConnector()

    result = execute_mirror_candidate_paper(
        candidate,
        equity_usdt=1_000.0,
        mid_price=25.0,
        top_depth_usdt=5_000.0,
        asks=((25.01, 20.0), (25.02, 20.0)),
        bids=((24.99, 20.0),),
        observed_at_ms=1_150,
        connector=connector,
    )

    assert result.accepted is True
    assert result.paper_result is not None
    assert result.paper_result.accepted is True
    payload = result.as_dict()
    assert payload["external_action"] is False
    assert payload["paper_only"] is True
    assert result.paper_result.fill is not None
    assert result.paper_result.fill.fill_id.startswith("psim_")
    assert "fill:leader:1" in result.evidence["candidate"]["source_fill_refs"]
    assert len(connector.fills) == 1


def test_mirror_conflicting_leaders_no_trade():
    long_candidate = mirror_candidate_from_delta(
        _delta(wallet="0x" + "a" * 40, action=LifecycleAction.OPEN_LONG, cur=5.0, evidence="fill:long"),
        leader_price=25.0,
        observed_time_ms=1_050,
        wallet_score=0.8,
        copyability_score=0.8,
    )
    short_candidate = mirror_candidate_from_delta(
        _delta(wallet="0x" + "b" * 40, action=LifecycleAction.OPEN_SHORT, cur=-5.0, evidence="fill:short"),
        leader_price=25.0,
        observed_time_ms=1_050,
        wallet_score=0.8,
        copyability_score=0.8,
    )

    decision = resolve_copy_conflicts([long_candidate, short_candidate])

    assert decision.accepted is False
    assert "CONFLICTING_LEADERS" in decision.reason_codes


def test_same_direction_leaders_boost_confidence():
    candidates = [
        mirror_candidate_from_delta(
            _delta(wallet="0x" + char * 40, action=LifecycleAction.OPEN_SHORT, cur=-10.0, evidence=f"fill:{char}"),
            leader_price=20.0,
            observed_time_ms=1_050,
            wallet_score=0.8,
            copyability_score=0.8,
        )
        for char in ("a", "b", "c")
    ]

    decision = resolve_copy_conflicts(candidates, min_same_side_leaders=2)

    assert decision.accepted is True
    assert decision.side == "SHORT"
    assert decision.confidence_boost > 0
    assert "SAME_DIRECTION_LEADERS" in decision.reason_codes


def test_candidate_to_paper_intent_is_paper_only():
    candidate = mirror_candidate_from_delta(
        _delta(action=LifecycleAction.INCREASE, prev=2.0, cur=3.5),
        leader_price=30.0,
        observed_time_ms=1_050,
        wallet_score=0.9,
        copyability_score=0.9,
    )

    intent = candidate_to_paper_intent(candidate, target_notional_usdt=12.0, created_at_ms=1_060)

    assert intent.action is IntentAction.ADD
    assert intent.simulation_only is True
    assert intent.requires_risk_approval is True
    assert any(item.startswith("candidate_id=") for item in intent.reasons)


def test_smart_money_watchlist_rejects_truncated_and_limits():
    watchlist = build_smart_money_watchlist(
        [
            {"wallet": "0x1234...abcd", "score": 1},
            {"wallet": "not-a-wallet", "score": 1},
            {"wallet": "0x" + "a" * 40, "score": 0.9, "source": "leaderboard"},
            {"wallet": "0x" + "b" * 40, "score": 0.8, "source": "leaderboard"},
        ],
        max_wallets=1,
        min_score=0.5,
    )

    assert watchlist.wallets == ("0x" + "a" * 40,)
    reasons = {row["reason"] for row in watchlist.rejected}
    assert "TRUNCATED_ADDRESS_REJECTED" in reasons
    assert "INVALID_ADDRESS_REJECTED" in reasons
    assert "WATCHLIST_LIMIT_REACHED" in reasons
