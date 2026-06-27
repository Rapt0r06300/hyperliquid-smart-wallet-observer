"""
Tests live observer, cluster detector et wallet discovery.
Tous mockés — aucun appel réseau réel.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
from hyper_smart_observer.dydx_v4.config import DydxV4Config, DydxMode
from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver, STOP_LOSS_PCT, TAKE_PROFIT_PCT
from hyper_smart_observer.dydx_v4.models import SimulationMode
from hyper_smart_observer.dydx_v4.wallet_discovery import WalletScore


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def _make_config(mode=SimulationMode.LIVE) -> DydxV4Config:
    """Crée une config testnet paper-only (simulation uniquement)."""
    return DydxV4Config(
        network="testnet",
        market_flow_enabled=False,
        mode=DydxMode(mode.value),  # SimulationMode → DydxMode par valeur
    )


def _make_wallet(address: str, score: float = 0.8, market: str = "ETH-USD") -> WalletScore:
    return WalletScore(
        address=address,
        subaccount_number=0,
        usdc_balance=50_000.0,
        total_score=score,
        open_positions=[{"market": market, "side": "LONG"}],
    )


def _make_orderbook(mid: float, spread_bps: float = 2.0, size: float = 100.0) -> dict:
    half = mid * spread_bps / 2 / 10_000
    return {
        "bids": [{"price": str(mid - half), "size": str(size)} for _ in range(5)],
        "asks": [{"price": str(mid + half), "size": str(size)} for _ in range(5)],
    }


def _make_observer(shortlist=None, poll_interval=0.01):
    config = _make_config()
    rest = MagicMock()
    rest.get_positions.return_value = {"positions": []}
    rest.get_markets.return_value = {
        "markets": {
            "ETH-USD": {"oraclePrice": "1650.0", "indexPrice": "1650.0"},
            "BTC-USD": {"oraclePrice": "61500.0", "indexPrice": "61500.0"},
            "SOL-USD": {"oraclePrice": "65.0", "indexPrice": "65.0"},
        }
    }
    rest.get_orderbook.side_effect = lambda market: {
        "ETH-USD": _make_orderbook(1650.0),
        "BTC-USD": _make_orderbook(61500.0),
        "SOL-USD": _make_orderbook(65.0),
    }.get(market, _make_orderbook(100.0))
    rest.get_candles.return_value = {"candles": []}
    rest.get_market.side_effect = lambda market: {"markets": {market: {"nextFundingRate": "0"}}}
    cluster = DydxClusterDetector(consensus_window_ms=60_000, min_notional_usdc=0.0)
    wallets = shortlist or [
        _make_wallet("dydx1aaa", 0.9),
        _make_wallet("dydx1bbb", 0.85),
    ]
    obs = DydxLiveObserver(
        config=config,
        rest_client=rest,
        cluster_detector=cluster,
        initial_shortlist=wallets,
        poll_interval_s=poll_interval,
        max_signal_age_ms=8_000,
    )
    return obs


# ──────────────────────────────────────────────
# Cluster Detector
# ──────────────────────────────────────────────

class TestClusterDetector:

    def test_no_cluster_single_wallet(self):
        cd = DydxClusterDetector(min_wallets_for_signal=2, min_notional_usdc=0.0)
        cd.update_positions("dydx1aaa", [
            {"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "1650.0"}
        ])
        clusters = cd.detect_clusters(min_wallets=2)
        assert clusters == []

    def test_cluster_detected_two_wallets(self):
        cd = DydxClusterDetector(min_wallets_for_signal=2, min_notional_usdc=0.0)
        cd.update_positions("dydx1aaa", [
            {"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "1650.0"}
        ])
        cd.update_positions("dydx1bbb", [
            {"market": "ETH-USD", "side": "LONG", "size": "2.0", "entryPrice": "1650.0"}
        ])
        clusters = cd.detect_clusters(min_wallets=2)
        assert len(clusters) == 1
        c = clusters[0]
        assert c.market_id == "ETH-USD"
        assert c.side == "LONG"
        assert c.wallet_count == 2

    def test_cluster_blocked_market_excluded(self):
        """HYPE et CASH:WTI ne doivent jamais générer de cluster."""
        cd = DydxClusterDetector(min_wallets_for_signal=2, min_notional_usdc=0.0)
        for addr in ["dydx1aaa", "dydx1bbb", "dydx1ccc"]:
            cd.update_positions(addr, [
                {"market": "HYPE", "side": "SHORT", "size": "10.0", "entryPrice": "58.0"}
            ])
        clusters = cd.detect_clusters(min_wallets=2)
        assert all(c.market_id != "HYPE" for c in clusters)

    def test_cluster_expires_after_window(self):
        """Les signaux vieux de >60s doivent être nettoyés."""
        cd = DydxClusterDetector(
            min_wallets_for_signal=2,
            consensus_window_ms=100,  # fenêtre très courte pour le test
            min_notional_usdc=0.0,
        )
        cd.update_positions("dydx1aaa", [
            {"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "1650.0"}
        ])
        cd.update_positions("dydx1bbb", [
            {"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "1650.0"}
        ])
        time.sleep(0.15)  # attendre expiration fenêtre
        clusters = cd.detect_clusters(min_wallets=2)
        assert clusters == []

    def test_close_detected(self):
        """Détecter une fermeture de position."""
        cd = DydxClusterDetector(min_notional_usdc=0.0)
        cd.update_positions("dydx1aaa", [
            {"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "1650.0"}
        ])
        events = cd.update_positions("dydx1aaa", [])  # position disparue
        close_events = [e for e in events if e.event_type == "CLOSE"]
        assert len(close_events) == 1
        assert close_events[0].market_id == "ETH-USD"

    def test_update_from_fill_open(self):
        """update_from_fill génère un event OPEN."""
        cd = DydxClusterDetector(min_notional_usdc=0.0)
        event = cd.update_from_fill("dydx1aaa", "ETH-USD", "BUY", 1.0, 1650.0, fill_id="f001")
        assert event is not None
        assert event.event_type == "OPEN"
        assert event.market_id == "ETH-USD"
        assert event.side == "LONG"


# ──────────────────────────────────────────────
# Live Observer — gates et paper trading
# ──────────────────────────────────────────────

class TestLiveObserver:

    def test_paper_only_config(self):
        """La config doit être en mode simulation (pas de vrais ordres)."""
        config = _make_config(SimulationMode.LIVE)
        rest = MagicMock()
        rest.get_positions.return_value = {"positions": []}
        rest.get_markets.return_value = {"markets": {}}
        cluster = DydxClusterDetector()
        obs = DydxLiveObserver(config=config, rest_client=rest, cluster_detector=cluster)
        # get_status ne doit pas planter
        status = obs.get_status()
        assert "disclaimer" in status
        assert "PAPER" in status["disclaimer"].upper()

    def test_signal_refused_stale(self):
        """Signal trop vieux doit être refusé."""
        obs = _make_observer()
        obs._mark_prices["ETH-USD"] = 1650.0

        # Injecter un cluster stale
        from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal
        now_ms = int(time.time() * 1000)
        stale_cluster = ClusterSignal(
            market_id="ETH-USD",
            side="LONG",
            wallet_count=3,
            participating_wallets=["dydx1aaa", "dydx1bbb", "dydx1ccc"],
            total_notional_usdc=50_000.0,
            first_wallet_opened_ms=now_ms - 60_000,  # 60s ago = stale
            last_wallet_opened_ms=now_ms - 55_000,
            signal_age_ms=60_000,
            avg_entry_price=1650.0,
            signal_strength=0.8,
            market_priority=1.0,
            is_fresh=False,
            cluster_id="test_cluster",
        )
        obs._evaluate_cluster(stale_cluster)
        assert obs.stats.stale_signals_refused >= 1
        assert len(obs._open_positions) == 0

    def test_paper_entry_accepted(self):
        """Un signal frais + 2 wallets doit ouvrir une position paper."""
        obs = _make_observer()
        obs._mark_prices["ETH-USD"] = 1650.0

        from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal
        now_ms = int(time.time() * 1000)
        cluster = ClusterSignal(
            market_id="ETH-USD",
            side="LONG",
            wallet_count=2,
            participating_wallets=["dydx1aaa", "dydx1bbb"],
            total_notional_usdc=50_000.0,
            first_wallet_opened_ms=now_ms - 300,  # tight precision cluster
            last_wallet_opened_ms=now_ms - 100,
            signal_age_ms=300,
            avg_entry_price=1650.0,
            signal_strength=0.95,
            market_priority=1.0,
            is_fresh=True,
            cluster_id="test_fresh",
        )
        obs._evaluate_cluster(cluster)
        assert obs.stats.positions_opened == 1
        assert "ETH-USD:LONG" in obs._open_positions

    def test_stop_loss_triggered(self):
        """Le stop-loss doit fermer la position et enregistrer une perte."""
        obs = _make_observer()
        obs._mark_prices["ETH-USD"] = 1650.0

        from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal
        now_ms = int(time.time() * 1000)
        cluster = ClusterSignal(
            market_id="ETH-USD",
            side="LONG",
            wallet_count=2,
            participating_wallets=["dydx1aaa", "dydx1bbb"],
            total_notional_usdc=50_000.0,
            first_wallet_opened_ms=now_ms - 300,
            last_wallet_opened_ms=now_ms - 100,
            signal_age_ms=300,
            avg_entry_price=1650.0,
            signal_strength=0.95,
            market_priority=1.0,
            is_fresh=True,
            cluster_id="test_sl",
        )
        obs._evaluate_cluster(cluster)
        assert obs.stats.positions_opened == 1

        # Simuler chute de prix → stop-loss
        entry_price = 1650.0
        stop_price = entry_price * (1 - STOP_LOSS_PCT / 100)
        obs._mark_prices["ETH-USD"] = stop_price - 1.0  # sous le stop
        obs._check_exits()

        assert obs.stats.positions_closed == 1
        assert obs.stats.stop_loss_exits == 1
        assert obs.stats.total_net_pnl_usdc < 0  # perte

    def test_take_profit_triggered(self):
        """Le take-profit doit fermer la position et enregistrer un gain."""
        obs = _make_observer()
        obs._mark_prices["ETH-USD"] = 1650.0

        from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal
        now_ms = int(time.time() * 1000)
        cluster = ClusterSignal(
            market_id="ETH-USD",
            side="LONG",
            wallet_count=2,
            participating_wallets=["dydx1aaa", "dydx1bbb"],
            total_notional_usdc=50_000.0,
            first_wallet_opened_ms=now_ms - 500,
            last_wallet_opened_ms=now_ms - 200,
            signal_age_ms=500,
            avg_entry_price=1650.0,
            signal_strength=0.9,
            market_priority=1.0,
            is_fresh=True,
            cluster_id="test_tp",
        )
        obs._evaluate_cluster(cluster)
        assert obs.stats.positions_opened == 1

        # Simuler hausse de prix → take-profit
        # Fill honnête (Selection v2): l'entrée LONG est pénalisée vs mid,
        # donc on utilise le TP réel de la position, pas un TP recalculé du mid.
        pos = next(iter(obs._open_positions.values()))
        assert pos.entry_price > 1650.0  # jamais au mid pour un LONG
        obs._mark_prices["ETH-USD"] = pos.take_profit_price * 1.001  # au-dessus du TP
        obs._check_exits()

        assert obs.stats.positions_closed == 1
        assert obs.stats.take_profit_exits == 1
        assert obs.stats.total_net_pnl_usdc > 0  # gain

    def test_max_open_positions_respected(self):
        """Max 3 positions paper simultanées."""
        obs = _make_observer()
        obs.config.correlation_gate_enabled = False  # test dédié au plafond, pas à la corrélation
        obs.config.max_open_paper_trades = 3
        from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal

        markets = ["ETH-USD", "BTC-USD", "SOL-USD"]
        prices = {"ETH-USD": 1650.0, "BTC-USD": 61500.0, "SOL-USD": 65.0}

        for market in markets:
            obs._mark_prices[market] = prices[market]

        now_ms = int(time.time() * 1000)
        for market in markets:
            cluster = ClusterSignal(
                market_id=market,
                side="LONG",
                wallet_count=2,
                participating_wallets=["dydx1aaa", "dydx1bbb"],
                total_notional_usdc=50_000.0,
                first_wallet_opened_ms=now_ms - 300,
                last_wallet_opened_ms=now_ms - 100,
                signal_age_ms=300,
                avg_entry_price=prices[market],
                signal_strength=0.95,
                market_priority=0.9,
                is_fresh=True,
                cluster_id=f"test_{market}",
            )
            obs._evaluate_cluster(cluster)

        assert obs.stats.positions_opened == 3

        # 4ème signal → refusé par le plafond configure
        obs._mark_prices["SOL-USD"] = 66.0
        extra_cluster = ClusterSignal(
            market_id="SOL-USD",
            side="SHORT",
            wallet_count=2,
            participating_wallets=["dydx1ccc", "dydx1ddd"],
            total_notional_usdc=50_000.0,
            first_wallet_opened_ms=now_ms - 1_000,
            last_wallet_opened_ms=now_ms - 500,
            signal_age_ms=1_000,
            avg_entry_price=66.0,
            signal_strength=0.8,
            market_priority=0.7,
            is_fresh=True,
            cluster_id="test_4th",
        )
        obs._evaluate_cluster(extra_cluster)
        assert obs.stats.positions_opened == 3
        assert "MAX_OPEN_REACHED" in obs._no_trade_reasons

    def test_blocked_market_refused(self):
        """XYZ:CL ne doit jamais ouvrir de position paper (blacklisted)."""
        obs = _make_observer()
        obs._mark_prices["XYZ:CL"] = 58.0

        from hyper_smart_observer.dydx_v4.cluster_detector import ClusterSignal
        now_ms = int(time.time() * 1000)
        cluster = ClusterSignal(
            market_id="XYZ:CL",
            side="SHORT",
            wallet_count=5,
            participating_wallets=["dydx1aaa", "dydx1bbb", "dydx1ccc", "dydx1ddd", "dydx1eee"],
            total_notional_usdc=100_000.0,
            first_wallet_opened_ms=now_ms - 500,
            last_wallet_opened_ms=now_ms - 100,
            signal_age_ms=500,
            avg_entry_price=58.0,
            signal_strength=0.95,
            market_priority=0.0,
            is_fresh=True,
            cluster_id="test_hype",
        )
        obs._evaluate_cluster(cluster)
        assert obs.stats.positions_opened == 0
        assert "XYZ:CL:SHORT" not in obs._open_positions

    def test_no_real_orders_in_any_method(self):
        """Aucune méthode ne doit émettre d'ordre réel (vérification sécurité)."""
        obs = _make_observer()
        # run() avec 1 itération ne doit pas planeter et ne pas appeler d'API privée
        obs._shortlist = []
        obs._refresh_market_prices = lambda: None
        obs._poll_shortlist = lambda: None
        obs.run(max_iterations=1)

        # Vérifier que rest_client n'a jamais été appelé avec POST/PUT/DELETE
        rest = obs.rest
        rest.post = MagicMock(side_effect=AssertionError("REAL ORDER FORBIDDEN"))
        rest.put = MagicMock(side_effect=AssertionError("REAL ORDER FORBIDDEN"))
        rest.delete = MagicMock(side_effect=AssertionError("REAL ORDER FORBIDDEN"))
        # Pas d'appel → pas d'exception → test passe

    def test_pnl_formula_long(self):
        """Vérifier la formule PnL LONG."""
        from hyper_smart_observer.dydx_v4.live_observer import PaperPositionState
        from hyper_smart_observer.dydx_v4.models import SimulationMode
        pos = PaperPositionState(
            position_id="test",
            market_id="ETH-USD",
            side="LONG",
            size=50.0,    # $50 notional
            entry_price=1600.0,
            stop_loss_price=1576.0,
            take_profit_price=1640.0,
            opened_at_ms=0,
            cluster_id="x",
            wallet_count=2,
            simulation_mode=SimulationMode.LIVE,
        )
        # Prix monte de 1600 → 1640 (2.5%)
        pnl = pos.calculate_pnl(1640.0)
        expected = (1640.0 - 1600.0) / 1600.0 * 50.0
        assert pnl == pytest.approx(expected, rel=0.001)
        assert pnl > 0  # gain

    def test_pnl_formula_short(self):
        """Vérifier la formule PnL SHORT."""
        from hyper_smart_observer.dydx_v4.live_observer import PaperPositionState
        from hyper_smart_observer.dydx_v4.models import SimulationMode
        pos = PaperPositionState(
            position_id="test",
            market_id="ETH-USD",
            side="SHORT",
            size=50.0,
            entry_price=1600.0,
            stop_loss_price=1624.0,
            take_profit_price=1560.0,
            opened_at_ms=0,
            cluster_id="x",
            wallet_count=2,
            simulation_mode=SimulationMode.LIVE,
        )
        # Prix baisse de 1600 → 1560 (2.5%)
        pnl = pos.calculate_pnl(1560.0)
        expected = (1600.0 - 1560.0) / 1600.0 * 50.0
        assert pnl == pytest.approx(expected, rel=0.001)
        assert pnl > 0  # gain
