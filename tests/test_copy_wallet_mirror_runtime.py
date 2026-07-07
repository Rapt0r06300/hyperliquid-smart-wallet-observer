from hl_observer.copy_wallet.wallet_mirror_runtime import run_wallet_mirror_pipeline
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta


def test_wallet_mirror_runtime_is_full_paper_pipeline() -> None:
    now_ms = 1_700_000_000_000
    delta = LeaderDelta(
        delta_id="unit:mirror",
        wallet="0x3333333333333333333333333333333333333333",
        coin="BTC",
        action=LifecycleAction.OPEN_SHORT,
        previous_size=0.0,
        current_size=-1.0,
        delta_size=-1.0,
        observed_at_ms=now_ms,
        leader_event_time_ms=now_ms - 50,
        source="fixture:test_copy_wallet_mirror_runtime",
        confidence=0.97,
        reason_codes=(),
    )

    result = run_wallet_mirror_pipeline(
        delta,
        leader_price=60_000,
        observed_time_ms=now_ms,
        wallet_score=0.97,
        copyability_score=0.96,
        leader_notional_usdt=250_000,
        current_mid=59_990,
        spread_bps=1,
        fee_bps=2,
        slippage_bps=2,
        latency_penalty_bps=1,
        leader_expected_edge_bps=75,
    )

    assert result.accepted is True
    assert result.paper_intent is not None
    assert result.paper_intent.coin == "BTC"
    assert result.paper_intent.simulation_only is True
    assert result.risk_decision.allow_new_entries is True
