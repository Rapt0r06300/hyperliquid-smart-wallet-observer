"""
Tests PnL et paper trading dYdX v4.

Tests obligatoires:
- PnL long correct: (mark - entry) * size
- PnL short correct: (entry - mark) * size
- frais non doublés
- séparation LIVE/BACKTEST/REPLAY
- fixtures exclues du PnL live
- partial reduce correct
- orphan close refusé
"""

from __future__ import annotations

import pytest

from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.models import (
    LifecycleEvent,
    NormalizedFill,
    OrderSide,
    PaperTrade,
    PaperTradeStatus,
    PositionSide,
    SignalCandidate,
    SimulationMode,
)
from hyper_smart_observer.dydx_v4.paper import DydxPaperSimulator


def make_signal(
    market_id: str = "BTC-USD",
    side: PositionSide = PositionSide.LONG,
    lifecycle: LifecycleEvent = LifecycleEvent.OPEN,
    age_ms: int = 1000,
    edge_bps: float = 100.0,
    mode: SimulationMode = SimulationMode.LIVE,
) -> SignalCandidate:
    import time, hashlib
    return SignalCandidate(
        signal_id=hashlib.sha256(f"{market_id}:{side}:{time.time()}".encode()).hexdigest()[:32],
        account_address="0xabc123def456",
        subaccount_number=0,
        market_id=market_id,
        side=side,
        lifecycle=lifecycle,
        size=0.1,
        price=50000.0,
        signal_age_ms=age_ms,
        edge_remaining_bps=edge_bps,
        total_cost_bps=20.0,
        source="test",
        simulation_mode=mode,
        created_at_ms=int(__import__("time").time() * 1000),
    )


class TestPnLFormulas:
    """Test les formules PnL obligatoires."""

    def test_long_pnl_profit(self):
        """LONG: (mark - entry) * size = (52000 - 50000) * 0.1 = 200.0"""
        trade = PaperTrade(
            trade_id="t1",
            account_address="0xabc",
            subaccount_number=0,
            market_id="BTC-USD",
            side=PositionSide.LONG,
            size=0.1,
            entry_price=50000.0,
            mark_price=52000.0,
            status=PaperTradeStatus.OPEN,
            lifecycle=LifecycleEvent.OPEN,
            gross_pnl=0,
            net_pnl=0,
            fees=0,
            spread_cost=0,
            slippage_cost=0,
            entry_at_ms=0,
            updated_at_ms=0,
        )
        gross, net = trade.compute_pnl(mark_price=52000.0, fee_bps=0.0)
        assert gross == pytest.approx(200.0, abs=0.01)
        assert net == pytest.approx(200.0, abs=0.01)  # fee=0

    def test_long_pnl_loss(self):
        """LONG: (48000 - 50000) * 0.1 = -200.0"""
        trade = PaperTrade(
            trade_id="t2",
            account_address="0xabc",
            subaccount_number=0,
            market_id="BTC-USD",
            side=PositionSide.LONG,
            size=0.1,
            entry_price=50000.0,
            mark_price=48000.0,
            status=PaperTradeStatus.OPEN,
            lifecycle=LifecycleEvent.OPEN,
            gross_pnl=0, net_pnl=0, fees=0, spread_cost=0, slippage_cost=0,
            entry_at_ms=0, updated_at_ms=0,
        )
        gross, net = trade.compute_pnl(mark_price=48000.0, fee_bps=0.0)
        assert gross == pytest.approx(-200.0, abs=0.01)

    def test_short_pnl_profit(self):
        """SHORT: (entry - mark) * size = (50000 - 48000) * 0.1 = 200.0"""
        trade = PaperTrade(
            trade_id="t3",
            account_address="0xabc",
            subaccount_number=0,
            market_id="BTC-USD",
            side=PositionSide.SHORT,
            size=0.1,
            entry_price=50000.0,
            mark_price=48000.0,
            status=PaperTradeStatus.OPEN,
            lifecycle=LifecycleEvent.OPEN,
            gross_pnl=0, net_pnl=0, fees=0, spread_cost=0, slippage_cost=0,
            entry_at_ms=0, updated_at_ms=0,
        )
        gross, net = trade.compute_pnl(mark_price=48000.0, fee_bps=0.0)
        assert gross == pytest.approx(200.0, abs=0.01)

    def test_short_pnl_loss(self):
        """SHORT: (50000 - 52000) * 0.1 = -200.0"""
        trade = PaperTrade(
            trade_id="t4",
            account_address="0xabc",
            subaccount_number=0,
            market_id="BTC-USD",
            side=PositionSide.SHORT,
            size=0.1,
            entry_price=50000.0,
            mark_price=52000.0,
            status=PaperTradeStatus.OPEN,
            lifecycle=LifecycleEvent.OPEN,
            gross_pnl=0, net_pnl=0, fees=0, spread_cost=0, slippage_cost=0,
            entry_at_ms=0, updated_at_ms=0,
        )
        gross, net = trade.compute_pnl(mark_price=52000.0, fee_bps=0.0)
        assert gross == pytest.approx(-200.0, abs=0.01)

    def test_fees_not_doubled_on_open(self):
        """Les frais aller-retour = 2x taker_fee_bps sur la notionnelle."""
        trade = PaperTrade(
            trade_id="t5",
            account_address="0xabc",
            subaccount_number=0,
            market_id="BTC-USD",
            side=PositionSide.LONG,
            size=1.0,
            entry_price=50000.0,
            mark_price=50000.0,
            status=PaperTradeStatus.OPEN,
            lifecycle=LifecycleEvent.OPEN,
            gross_pnl=0, net_pnl=0, fees=0, spread_cost=0, slippage_cost=0,
            entry_at_ms=0, updated_at_ms=0,
        )
        fee_bps = 5.0
        gross, net = trade.compute_pnl(mark_price=50000.0, fee_bps=fee_bps)
        expected_rt_fees = 1.0 * 50000.0 * (fee_bps / 10_000) * 2  # aller + retour
        assert abs(gross - net) == pytest.approx(expected_rt_fees, rel=0.01)


class TestPaperSimulator:
    def setup_method(self):
        self.config = DydxV4Config()
        self.sim = DydxPaperSimulator(self.config)

    def test_open_position(self):
        signal = make_signal()
        trade = self.sim.open_position(signal, mark_price=50000.0)
        assert trade is not None
        assert trade.status == PaperTradeStatus.OPEN
        assert trade.entry_price > 0
        assert trade.fees > 0
        assert "PAPER SIMULATION" in trade.notes[0]

    def test_orphan_close_refused(self):
        """Fermer une position qui n'existe pas doit retourner None."""
        result = self.sim.close_position(
            position_key="dydx_v4|0xnever|0|BTC-USD|LONG",
            mark_price=52000.0,
            mode=SimulationMode.LIVE,
        )
        assert result is None

    def test_close_position_pnl(self):
        signal = make_signal()
        trade = self.sim.open_position(signal, mark_price=50000.0)
        assert trade is not None

        # Mettre à jour mark price
        self.sim.update_mark_price(
            trade.position_key, mark_price=52000.0, mode=SimulationMode.LIVE
        )

        # Fermer
        close = self.sim.close_position(
            position_key=trade.position_key,
            mark_price=52000.0,
            close_reason="TEST",
            mode=SimulationMode.LIVE,
        )
        assert close is not None
        assert close.gross_pnl > 0  # LONG profite quand price monte
        assert close.fees > 0

    def test_live_backtest_separation(self):
        """Les PnL LIVE et BACKTEST doivent être séparés."""
        signal_live = make_signal(mode=SimulationMode.LIVE)
        signal_bt = make_signal(mode=SimulationMode.BACKTEST)

        trade_live = self.sim.open_position(signal_live, mark_price=50000.0)
        trade_bt = self.sim.open_position(signal_bt, mark_price=50000.0)

        stats_live = self.sim.get_session_stats(SimulationMode.LIVE)
        stats_bt = self.sim.get_session_stats(SimulationMode.BACKTEST)

        assert stats_live["open_positions"] == 1
        assert stats_bt["open_positions"] == 1
        # Les balances sont indépendantes
        assert stats_live["starting_balance_usdc"] == stats_bt["starting_balance_usdc"]

    def test_max_open_trades_enforced(self):
        """Le max_open_paper_trades doit être respecté."""
        cfg = DydxV4Config(max_open_paper_trades=2)
        sim = DydxPaperSimulator(cfg)

        s1 = make_signal(market_id="BTC-USD")
        s2 = make_signal(market_id="ETH-USD")
        s3 = make_signal(market_id="SOL-USD")

        t1 = sim.open_position(s1, mark_price=50000.0)
        t2 = sim.open_position(s2, mark_price=2000.0)
        t3 = sim.open_position(s3, mark_price=100.0)

        assert t1 is not None
        assert t2 is not None
        assert t3 is None  # Bloqué par max_open_paper_trades=2

    def test_session_stats_are_read_only(self):
        """get_session_stats ne doit pas modifier l'état."""
        stats1 = self.sim.get_session_stats(SimulationMode.LIVE)
        stats2 = self.sim.get_session_stats(SimulationMode.LIVE)
        assert stats1 == stats2

    def test_paper_only_confirmed_in_stats(self):
        stats = self.sim.get_session_stats(SimulationMode.LIVE)
        assert stats["paper_only"] is True
        assert stats["no_real_orders"] is True
        assert stats["no_real_money"] is True

    def test_partial_reduce(self):
        """Un partial reduce doit réduire la taille mais garder la position ouverte."""
        signal = make_signal()
        trade = self.sim.open_position(signal, mark_price=50000.0)
        assert trade is not None

        session = self.sim._get_session(SimulationMode.LIVE)
        pos = session.open_positions.get(trade.position_key)
        assert pos is not None
        full_size = pos.size

        # Partial close (50%)
        partial_close = self.sim.close_position(
            position_key=trade.position_key,
            mark_price=51000.0,
            mode=SimulationMode.LIVE,
            partial_size=full_size * 0.5,
        )
        assert partial_close is not None
        assert partial_close.lifecycle == LifecycleEvent.REDUCE

        # Position toujours ouverte mais réduite
        pos_after = session.open_positions.get(trade.position_key)
        assert pos_after is not None
        assert pos_after.size == pytest.approx(full_size * 0.5, rel=0.01)


class TestModeIsolation:
    """PnL LIVE ne doit jamais contenir BACKTEST, REPLAY ou TEST_FIXTURE."""

    def test_test_fixture_never_in_live_pnl(self):
        """Signaux avec adresse fixture ne doivent jamais entrer dans LIVE PnL."""
        from hyper_smart_observer.dydx_v4.safety import is_test_fixture_account
        assert is_test_fixture_account("0x1111111111111111111111111111111111111111") is True
        assert is_test_fixture_account("0x2222222222222222222222222222222222222222") is True
        assert is_test_fixture_account("0xabc123def456") is False

    def test_backtest_pnl_stays_in_backtest(self):
        from hyper_smart_observer.dydx_v4.backtest import DydxBacktester
        from hyper_smart_observer.dydx_v4.models import NormalizedFill, OrderSide
        cfg = DydxV4Config()
        bt = DydxBacktester(cfg)

        fills = [
            NormalizedFill(
                fill_id="f1", account_address="0xabc", subaccount_number=0,
                market_id="BTC-USD", side=OrderSide.BUY, size=0.1, price=50000.0,
                fee=25.0, liquidity="TAKER", created_at_ms=1000,
            ),
            NormalizedFill(
                fill_id="f2", account_address="0xabc", subaccount_number=0,
                market_id="BTC-USD", side=OrderSide.SELL, size=0.1, price=52000.0,
                fee=26.0, liquidity="TAKER", created_at_ms=2000,
            ),
        ]

        result = bt.run_on_fills(fills, mode=SimulationMode.BACKTEST)
        assert result.total_trades == 1
        assert result.net_pnl > 0  # Long profitable
        assert "BACKTEST" in result.disclaimer

    def test_backtest_cannot_use_live_mode(self):
        from hyper_smart_observer.dydx_v4.backtest import DydxBacktester
        cfg = DydxV4Config()
        bt = DydxBacktester(cfg)
        with pytest.raises(ValueError, match="LIVE"):
            bt.run_on_fills([], mode=SimulationMode.LIVE)
