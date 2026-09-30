from pathlib import Path

from hl_observer.copy_wallet.proportional_sizer import ProportionalSizingConfig, size_proportional_to_leader
from hl_observer.copy_wallet.slippage_budget import evaluate_slippage_budget
from hl_observer.copy_wallet.wallet_mirror_runtime import run_wallet_mirror_pipeline
from hl_observer.copy_wallet.wallet_rank_decay import apply_wallet_rank_decay
from hl_observer.copy_wallet.wallet_tier import tier_for_wallet_score
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.risk.risk_engine_v3 import SessionEntryRiskContext
from hl_observer.signals.leader_delta import LeaderDelta


def _leader_delta(now_ms: int) -> LeaderDelta:
    return LeaderDelta(
        delta_id="test:leader:open_long",
        wallet="0x2222222222222222222222222222222222222222",
        coin="HYPE",
        action=LifecycleAction.OPEN_LONG,
        previous_size=0.0,
        current_size=20.0,
        delta_size=20.0,
        observed_at_ms=now_ms,
        leader_event_time_ms=now_ms - 100,
        source="fixture:wallet_copy_e2e",
        confidence=0.98,
        reason_codes=(),
        evidence_ref="fill:test:1",
    )


def test_wallet_copy_e2e_builds_paper_intent_and_journal(tmp_path: Path) -> None:
    result = run_wallet_mirror_pipeline(
        _leader_delta(1_700_000_000_000),
        leader_price=100.0,
        observed_time_ms=1_700_000_000_000,
        wallet_score=0.99,
        copyability_score=0.95,
        wallet_rank=1,
        wallet_rank_age_ms=1_000,
        leader_notional_usdt=100_000,
        current_mid=100.02,
        spread_bps=1.0,
        fee_bps=2.0,
        slippage_bps=1.5,
        latency_penalty_bps=0.5,
        logs_dir=tmp_path,
        leader_expected_edge_bps=80.0,
    )

    assert result.accepted is True
    assert result.paper_intent is not None
    assert result.paper_intent.simulation_only is True
    assert result.risk_decision.allow_new_entries is True
    assert result.edge_estimate.accepted is True
    assert result.journal_record is not None
    assert result.journal_record.real_execution is False
    assert (tmp_path / "wallet_mirror_journal.jsonl").exists()


def test_wallet_copy_e2e_rejects_when_edge_after_cost_is_too_low(tmp_path: Path) -> None:
    result = run_wallet_mirror_pipeline(
        _leader_delta(1_700_000_010_000),
        leader_price=100.0,
        observed_time_ms=1_700_000_010_000,
        wallet_score=0.99,
        copyability_score=0.95,
        leader_notional_usdt=100_000,
        current_mid=100.02,
        spread_bps=10.0,
        fee_bps=5.0,
        slippage_bps=8.0,
        latency_penalty_bps=2.0,
        logs_dir=tmp_path,
        leader_expected_edge_bps=20.0,
    )

    assert result.accepted is False
    assert result.paper_intent is None
    assert "EDGE_REMAINING_TOO_LOW" in result.no_trade_reasons
    assert result.journal_record is not None


def test_wallet_copy_e2e_blocks_entry_when_session_fee_drag_is_bad(tmp_path: Path) -> None:
    result = run_wallet_mirror_pipeline(
        _leader_delta(1_700_000_020_000),
        leader_price=100.0,
        observed_time_ms=1_700_000_020_000,
        wallet_score=0.99,
        copyability_score=0.95,
        leader_notional_usdt=30_000,
        current_mid=100.01,
        spread_bps=1.0,
        fee_bps=2.0,
        slippage_bps=1.0,
        latency_penalty_bps=0.5,
        logs_dir=tmp_path,
        leader_expected_edge_bps=45.0,
        session_risk_context=SessionEntryRiskContext(
            net_pnl_usdc=-0.29,
            fee_drag_ratio=0.52,
            consecutive_losses=4,
            top_losing_coins=(("HYPE", -0.25),),
        ),
    )

    assert result.accepted is False
    assert result.paper_intent is None
    assert "FEE_DRAG_GUARD_ACTIVE" in result.no_trade_reasons
    assert "NO_MICRO_TRADE_NOTIONAL" in result.no_trade_reasons
    assert "ENTRY_EDGE_BELOW_SESSION_REQUIREMENT" in result.no_trade_reasons
    assert result.entry_cost_guard.accepted is False
    assert result.journal_record is not None
    assert result.journal_record.real_execution is False


def test_copy_wallet_helpers_match_tier_sizing_rank_and_slippage() -> None:
    decayed = apply_wallet_rank_decay(base_score=1.0, rank=1, age_ms=0)
    tier = tier_for_wallet_score(decayed.decayed_score, 0.95)
    sizing = size_proportional_to_leader(
        leader_notional_usdt=100_000,
        tier=tier,
        config=ProportionalSizingConfig(follower_equity_usdt=1000, leader_equity_usdt=100_000),
    )
    slippage = evaluate_slippage_budget(
        requested_budget_bps=18,
        tier=tier,
        spread_bps=1,
        estimated_slippage_bps=2,
        latency_penalty_bps=1,
    )

    assert tier.name == "S"
    assert sizing.accepted is True
    assert sizing.margin_usdt > 0
    assert slippage.accepted is True
