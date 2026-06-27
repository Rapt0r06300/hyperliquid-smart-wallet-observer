from __future__ import annotations
import pytest

import json
import time
from unittest.mock import MagicMock

from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal, DydxClusterDetector
from hyper_smart_observer.dydx_v4.config import DydxNetwork, DydxV4Config
from hyper_smart_observer.dydx_v4.leader_quality import score_trades_by_market
from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver, PaperPositionState
from hyper_smart_observer.dydx_v4.scoring import TradeRecord
from hyper_smart_observer.dydx_v4.wallet_discovery import WalletScore


def _book(mid: float = 100.0, spread_bps: float = 2.0, size: float = 100.0) -> dict:
    half = mid * spread_bps / 2 / 10_000
    return {
        "bids": [{"price": str(mid - half), "size": str(size)} for _ in range(5)],
        "asks": [{"price": str(mid + half), "size": str(size)} for _ in range(5)],
    }


def _candles(values: list[float]) -> dict:
    return {
        "candles": [
            {
                "startedAt": f"2026-01-01T00:{i:02d}:00.000Z",
                "open": str(close),
                "high": str(close * 1.002),
                "low": str(close * 0.998),
                "close": str(close),
                "baseTokenVolume": "1000",
            }
            for i, close in enumerate(values)
        ]
    }


def _cluster(
    *,
    wallets: list[str],
    first_age_ms: int = 20_000,
    last_age_ms: int = 200,
) -> ClusterSignal:
    now_ms = int(time.time() * 1000)
    return ClusterSignal(
        market_id="ETH-USD",
        side="LONG",
        wallet_count=len(wallets),
        participating_wallets=wallets,
        total_notional_usdc=100_000.0,
        first_wallet_opened_ms=now_ms - first_age_ms,
        last_wallet_opened_ms=now_ms - last_age_ms,
        signal_age_ms=last_age_ms,
        avg_entry_price=100.0,
        signal_strength=0.95,
        market_priority=1.0,
        is_fresh=True,
        cluster_id=f"cluster-{now_ms}-{len(wallets)}",
    )


def _wallet(address: str, *, eth_expectancy: float) -> WalletScore:
    return WalletScore(
        address=address,
        total_score=0.9,
        net_pnl_usdc=2_000.0,
        winrate=0.7,
        profit_factor=2.5,
        trade_count=80,
        recent_score=1.0,
        market_stats={
            "ETH-USD": {
                "trade_count": 24,
                "winrate": 0.7 if eth_expectancy > 0 else 0.2,
                "profit_factor": 2.2 if eth_expectancy > 0 else 0.4,
                "expectancy_usdc": eth_expectancy,
                "net_pnl_usdc": eth_expectancy * 24,
                "recent_score": 1.0,
                "confidence": 1.0,
            }
        },
    )


def _observer(rest: MagicMock, wallets: list[WalletScore], **cfg_overrides) -> DydxLiveObserver:
    cfg = DydxV4Config(
        network=DydxNetwork.TESTNET,
        market_flow_enabled=False,
        consensus_min_wallets=1,
        max_open_paper_trades=3,
        min_edge_bps=3.0,
        **cfg_overrides,
    )
    rest.get_orderbook.return_value = _book()
    up = _candles([100 + i for i in range(30)])
    rest.get_candles.side_effect = [up, up, up]
    rest.get_market.return_value = {"markets": {"ETH-USD": {"nextFundingRate": "0"}}}
    obs = DydxLiveObserver(
        config=cfg,
        rest_client=rest,
        cluster_detector=DydxClusterDetector(consensus_window_ms=60_000, min_notional_usdc=0.0),
        initial_shortlist=wallets,
        poll_interval_s=0.01,
        max_signal_age_ms=8_000,
    )
    obs._mark_prices["ETH-USD"] = 100.0
    return obs


def test_score_trades_by_market_separates_good_and_bad_markets() -> None:
    now_ms = int(time.time() * 1000)
    trades = [
        TradeRecord(10, 10, 1, 1000, 100, now_ms - 1_000, 60_000, "ETH-USD"),
        TradeRecord(8, 8, 1, 1000, 100, now_ms - 2_000, 60_000, "ETH-USD"),
        TradeRecord(-5, -5, 1, 1000, 50, now_ms - 3_000, 60_000, "SOL-USD"),
    ]

    scores = score_trades_by_market(trades, current_ts_ms=now_ms, confidence_full_trades=2)

    assert scores["ETH-USD"].winrate == 1.0
    assert scores["ETH-USD"].expectancy_usdc == 9.0
    assert scores["SOL-USD"].winrate == 0.0


def test_market_specific_bad_leader_stats_refuse_even_if_aggregate_wallet_is_good() -> None:
    rest = MagicMock()
    wallets = [_wallet("dydx1badeth", eth_expectancy=-2.0)]
    obs = _observer(rest, wallets)

    obs._evaluate_cluster(_cluster(wallets=["dydx1badeth"]))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("EDGE_INSUFFICIENT") for reason in obs._no_trade_reasons)


def test_recent_consensus_and_market_leader_stats_are_logged_on_accept() -> None:
    rest = MagicMock()
    wallets = [_wallet("dydx1goodeth", eth_expectancy=8.0)]
    obs = _observer(rest, wallets)

    obs._evaluate_cluster(_cluster(wallets=["dydx1goodeth"], first_age_ms=20_000, last_age_ms=100))

    assert obs.stats.positions_opened == 1
    pos = next(iter(obs._open_positions.values()))
    assert "RECENT_CONSENSUS" in pos.sizing_reason
    assert "leader_market" in pos.sizing_reason


def test_adverse_funding_cost_is_subtracted_before_paper_entry() -> None:
    rest = MagicMock()
    wallets = [_wallet("dydx1goodeth", eth_expectancy=8.0)]
    obs = _observer(rest, wallets, funding_edge_horizon_hours=1.0)
    rest.get_market.return_value = {"markets": {"ETH-USD": {"nextFundingRate": "0.02"}}}

    obs._evaluate_cluster(_cluster(wallets=["dydx1goodeth"], first_age_ms=10_000, last_age_ms=100))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("EDGE_INSUFFICIENT") for reason in obs._no_trade_reasons)


def test_no_trade_is_written_to_append_only_decision_log(tmp_path) -> None:
    rest = MagicMock()
    path = tmp_path / "decisions.jsonl"
    obs = _observer(
        rest,
        [_wallet("dydx1goodeth", eth_expectancy=8.0)],
        decision_log_path=str(path),
    )

    obs._refuse("TEST_REFUSAL detail=unit")

    rows = obs.get_recent_decisions(limit=5, event_type="NO_TRADE")
    assert path.exists()
    assert len(rows) == 1
    assert rows[0]["reason"] == "TEST_REFUSAL"
    assert rows[0]["paper_only"] is True
    assert rows[0]["read_only"] is True
    assert rows[0]["session_id"] == obs.stats.session_id
    assert rows[0]["net_pnl_usdc"] == 0.0
    assert rows[0]["equity_usdc"] == 1000.0


def test_atr_take_profit_takes_partial_and_keeps_runner(tmp_path) -> None:
    rest = MagicMock()
    obs = _observer(
        rest,
        [_wallet("dydx1goodeth", eth_expectancy=8.0)],
        decision_log_path=str(tmp_path / "decisions.jsonl"),
    )
    pos = PaperPositionState(
        position_id="p1",
        market_id="ETH-USD",
        side="LONG",
        size=100.0,
        entry_price=100.0,
        stop_loss_price=98.0,
        take_profit_price=106.0,
        opened_at_ms=int(time.time() * 1000) - 10_000,
        cluster_id="c1",
        wallet_count=3,
        fee_paid=0.05,
        exit_method="ATR",
        initial_size=100.0,
        first_take_profit_price=106.0,
    )
    obs._open_positions["ETH-USD:LONG"] = pos
    obs._mark_prices["ETH-USD"] = 106.0

    obs._check_exits()

    assert "ETH-USD:LONG" in obs._open_positions
    assert obs.stats.positions_closed == 0
    assert obs.stats.partial_take_profit_exits == 1
    assert obs._open_positions["ETH-USD:LONG"].size == 50.0
    assert obs._open_positions["ETH-USD:LONG"].stop_loss_price == 100.0
    assert obs._open_positions["ETH-USD:LONG"].take_profit_price == 112.0
    rows = obs.get_recent_decisions(limit=5, event_type="PAPER_PARTIAL_TP")
    assert rows and rows[-1]["reason"] == "TAKE_PROFIT_PARTIAL"


def test_weak_two_wallet_precision_cluster_is_refused() -> None:
    rest = MagicMock()
    wallets = [
        _wallet("dydx1gooda", eth_expectancy=8.0),
        _wallet("dydx1goodb", eth_expectancy=8.0),
    ]
    obs = _observer(rest, wallets)

    obs._evaluate_cluster(_cluster(wallets=["dydx1gooda", "dydx1goodb"], first_age_ms=900, last_age_ms=450))

    assert obs.stats.positions_opened == 0
    assert any(reason.startswith("PRECISION_CLUSTER_TOO_WEAK") for reason in obs._no_trade_reasons)


def test_tight_two_wallet_precision_cluster_is_accepted() -> None:
    rest = MagicMock()
    wallets = [
        _wallet("dydx1gooda", eth_expectancy=8.0),
        _wallet("dydx1goodb", eth_expectancy=8.0),
    ]
    obs = _observer(rest, wallets)

    obs._evaluate_cluster(_cluster(wallets=["dydx1gooda", "dydx1goodb"], first_age_ms=300, last_age_ms=100))

    assert obs.stats.positions_opened == 1
    pos = next(iter(obs._open_positions.values()))
    assert "RECENT_CONSENSUS" in pos.sizing_reason


def test_market_side_performance_bootstraps_from_decision_log(tmp_path) -> None:
    decision_log = tmp_path / "decisions.jsonl"
    now_ms = int(time.time() * 1000) - 60_000
    rows = [
        {
            "event_type": "PAPER_CLOSE",
            "market_id": "ETH-USD",
            "side": "LONG",
            "net_pnl": -0.30,
            "closed_at_ms": now_ms,
            "paper_only": True,
            "read_only": True,
        },
        {
            "event_type": "PAPER_CLOSE",
            "market_id": "ETH-USD",
            "side": "LONG",
            "net_pnl": -0.20,
            "closed_at_ms": now_ms + 1_000,
            "paper_only": True,
            "read_only": True,
        },
    ]
    decision_log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    rest = MagicMock()
    obs = _observer(
        rest,
        [_wallet("dydx1goodeth", eth_expectancy=8.0)],
        decision_log_path=str(decision_log),
        market_side_history_bootstrap_trades=20,
        market_side_loss_cooldown_seconds=0,
        market_side_min_edge_after_loss_bps=30.0,
    )

    row = obs._market_side_perf[("ETH-USD", "LONG")]
    assert row["losses"] == 2
    assert row["consecutive_losses"] == 2
    reason = obs._market_side_performance_block_reason("ETH-USD", "LONG", 4.0)
    assert reason is not None
    assert reason.startswith("MARKET_SIDE_EDGE_AFTER_LOSS")

