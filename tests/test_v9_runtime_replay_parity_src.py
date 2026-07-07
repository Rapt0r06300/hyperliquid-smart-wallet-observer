from __future__ import annotations

from hl_observer.backtest import compare_runtime_replay_paper
from hl_observer.features import build_market_feature_vector
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.storage.run_context import RunContext


def _signal(edge: float = 60.0) -> SignalCandidate:
    return SignalCandidate(
        id="sig-parity",
        source_wallet="0x" + "c" * 40,
        coin="ETH",
        side="short",
        signal_type="open",
        observed_price=2000.0,
        timestamp_ms=1_800_000_400_000,
        signal_age_ms=200,
        wallet_score=91,
        signal_score=88,
        edge_remaining_bps=edge,
        estimated_spread_bps=2.0,
        estimated_slippage_bps=3.0,
        orderbook_depth_usdc=100_000,
    )


def _market():
    return build_market_feature_vector(
        timestamp_ms=1_800_000_400_000,
        source_ts_ms=1_800_000_399_900,
        coin="ETH",
        l2_book={
            "levels": [
                [{"px": "1999.9", "sz": "50"}],
                [{"px": "2000.1", "sz": "50"}],
            ]
        },
        all_mids={"ETH": "2000"},
        candles=[
            {"c": "2000", "h": "2001", "l": "1999", "T": "1800000000000"},
            {"c": "1999.8", "h": "2000.8", "l": "1998.8", "T": "1800000060000"},
            {"c": "1999.7", "h": "2000.7", "l": "1998.7", "T": "1800000120000"},
        ],
    )


def test_v9_runtime_replay_paper_economics_match_but_pnl_contexts_do_not_merge() -> None:
    result = compare_runtime_replay_paper(signal=_signal(), market=_market(), notional_usdc=123.0)

    assert result.runtime_scope.context == RunContext.LIVE
    assert result.replay_scope.context == RunContext.REPLAY
    assert result.economics_match is True
    assert result.risk_match is True
    assert result.pnl_may_merge is False
    assert result.warnings == ()
    assert result.runtime_decision.paper_order.simulated_fill_price == result.replay_decision.paper_order.simulated_fill_price
    assert result.runtime_decision.evidence.evidence_hash != result.replay_decision.evidence.evidence_hash


def test_v9_runtime_replay_parity_also_matches_no_trade_path() -> None:
    result = compare_runtime_replay_paper(signal=_signal(edge=5.0), market=_market(), notional_usdc=123.0)

    assert result.economics_match is True
    assert result.risk_match is True
    assert result.runtime_decision.accepted is False
    assert result.replay_decision.accepted is False
    assert result.runtime_decision.paper_order.notional_usdc == 0.0
    assert result.warnings == ()
