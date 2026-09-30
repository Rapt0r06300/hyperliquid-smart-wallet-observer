from __future__ import annotations

from hl_observer.copying import build_risk_context_from_signal, run_paper_simulation_decision
from hl_observer.features import build_market_feature_vector
from hl_observer.hyperliquid.schemas import SignalCandidate, SignalDecision


def _signal(edge: float = 60.0) -> SignalCandidate:
    return SignalCandidate(
        id="sig-pipeline",
        source_wallet="0x" + "b" * 40,
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=100.005,
        timestamp_ms=1_800_000_300_000,
        signal_age_ms=250,
        wallet_score=92,
        signal_score=86,
        edge_remaining_bps=edge,
        estimated_spread_bps=2.0,
        estimated_slippage_bps=3.0,
        orderbook_depth_usdc=25_000,
    )


def _clean_market():
    return build_market_feature_vector(
        timestamp_ms=1_800_000_300_000,
        source_ts_ms=1_800_000_299_900,
        coin="BTC",
        l2_book={
            "levels": [
                [{"px": "100.00", "sz": "100"}],
                [{"px": "100.01", "sz": "100"}],
            ]
        },
        all_mids={"BTC": "100.005"},
        candles=[
            {"c": "100.0", "h": "100.1", "l": "99.9", "T": "1800000000000"},
            {"c": "100.01", "h": "100.11", "l": "99.91", "T": "1800000060000"},
            {"c": "100.02", "h": "100.12", "l": "99.92", "T": "1800000120000"},
        ],
    )


def test_v9_simulation_pipeline_allows_only_after_market_and_risk_pass() -> None:
    signal = _signal()
    market = _clean_market()

    decision = run_paper_simulation_decision(
        signal=signal,
        market=market,
        run_id="pipeline/1",
        notional_usdc=100.0,
    )

    assert decision.accepted is True
    assert decision.risk_decision.allowed is True
    assert decision.risk_decision.decision == SignalDecision.PAPER_TRADE
    assert decision.paper_order.notional_usdc == 100.0
    assert decision.paper_order.simulated_fill_price > signal.observed_price
    assert decision.evidence.feature_hash == market.feature_hash
    assert decision.evidence.decision_type == "PAPER_SIMULATED"


def test_v9_simulation_pipeline_market_penalty_changes_risk_context() -> None:
    signal = _signal(edge=60.0)
    market = _clean_market()
    context = build_risk_context_from_signal(signal, market)

    assert context.edge_remaining_bps == signal.edge_remaining_bps
    assert context.spread_bps == market.spread_bps
    assert context.orderbook_depth_usdc == market.bid_depth_usdc + market.ask_depth_usdc
    assert context.data_gap is False


def test_v9_simulation_pipeline_blocks_stale_wide_market_before_paper_notional() -> None:
    signal = _signal(edge=70.0)
    bad_market = build_market_feature_vector(
        timestamp_ms=1,
        coin="BTC",
        l2_book={"levels": [[{"px": "90", "sz": "0.1"}], [{"px": "110", "sz": "0.1"}]]},
        is_stale=True,
        max_spread_bps=10,
        min_liquidity_score=50,
    )

    decision = run_paper_simulation_decision(
        signal=signal,
        market=bad_market,
        run_id="pipeline/2",
        notional_usdc=100.0,
    )

    assert decision.accepted is False
    assert decision.paper_order.notional_usdc == 0.0
    assert decision.risk_decision.allowed is False
    assert decision.evidence.decision_type != "PAPER_SIMULATED"
    assert "SPREAD_TOO_WIDE" in decision.reasons
    assert decision.evidence.paper_rejected_reason


def test_v9_simulation_pipeline_missing_market_is_no_trade_with_evidence() -> None:
    decision = run_paper_simulation_decision(
        signal=_signal(edge=60.0),
        market=None,
        run_id="pipeline/3",
        notional_usdc=100.0,
    )

    assert decision.accepted is False
    assert decision.risk_context.data_gap is True
    assert decision.evidence.feature_hash is None
    assert decision.evidence.market_quality_reasons == ("MARKET_FEATURES_MISSING",)
