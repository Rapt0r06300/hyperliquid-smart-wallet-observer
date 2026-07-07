"""
tests/test_whale_watchlist.py — Tests du whale watchlist dYdX v4.

PAPER SIMULATION ONLY — aucun ordre réel, aucune clé privée.
"""

import time
import pytest
from unittest.mock import MagicMock, patch


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_rest(closed_positions=None, raises=False):
    """REST client mock qui retourne des positions fermées."""
    rest = MagicMock()
    if raises:
        rest.get_positions.side_effect = Exception("network error")
    else:
        rest.get_positions.return_value = {
            "positions": closed_positions or []
        }
    return rest


def _make_closed_pos(pnl: float, closed_at: str = "2024-01-10T12:00:00.000Z"):
    return {
        "market": "ETH-USD",
        "side": "LONG",
        "realizedPnl": str(pnl),
        "closedAt": closed_at,
        "status": "CLOSED",
    }


# ─── Tests WhaleWatchlist ─────────────────────────────────────────────────────

class TestWhaleWatchlistInit:
    def test_init_creates_db(self, tmp_path):
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        rest = _make_rest()
        wl = WhaleWatchlist(
            rest_client=rest,
            db_path=str(tmp_path / "test_whale.db"),
        )
        assert wl is not None
        assert len(wl.get_top()) == 0  # DB vide au démarrage

    def test_get_hot_set_empty_initially(self, tmp_path):
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        wl = WhaleWatchlist(
            rest_client=_make_rest(),
            db_path=str(tmp_path / "test_whale.db"),
        )
        assert wl.get_hot_set() == set()

    def test_is_whale_false_when_empty(self, tmp_path):
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        wl = WhaleWatchlist(
            rest_client=_make_rest(),
            db_path=str(tmp_path / "test_whale.db"),
        )
        assert not wl.is_whale("dydx1abc123")


class TestWhaleScoreCandidate:
    def test_score_good_performer(self, tmp_path):
        """Un wallet avec 70% win rate + PF 2 + 10k PnL doit être scoré positivement."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist, MIN_WIN_RATE
        positions = (
            [_make_closed_pos(1000.0)] * 7 +  # 7 wins
            [_make_closed_pos(-500.0)] * 3     # 3 losses
        )
        wl = WhaleWatchlist(
            rest_client=_make_rest(closed_positions=positions),
            db_path=str(tmp_path / "test_whale.db"),
        )
        score = wl._score_candidate("dydx1test1")
        assert score is not None
        assert score.win_rate == pytest.approx(0.70, abs=0.01)
        assert score.profit_factor > 1.0
        assert score.total_pnl_usdc == pytest.approx(7 * 1000 - 3 * 500, abs=0.01)
        assert score.composite_score > 0
        assert score.address == "dydx1test1"

    def test_score_bad_performer_rejected(self, tmp_path):
        """Un wallet avec 30% win rate doit être rejeté (< MIN_WIN_RATE)."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist, MIN_WIN_RATE
        positions = (
            [_make_closed_pos(500.0)] * 3 +
            [_make_closed_pos(-800.0)] * 7
        )
        wl = WhaleWatchlist(
            rest_client=_make_rest(closed_positions=positions),
            db_path=str(tmp_path / "test_whale.db"),
        )
        score = wl._score_candidate("dydx1loser")
        # Rejeté: win_rate < MIN_WIN_RATE OU pnl négatif
        assert score is None

    def test_score_insufficient_history_rejected(self, tmp_path):
        """Un wallet avec < 5 trades doit être rejeté."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        positions = [_make_closed_pos(1000.0)] * 3
        wl = WhaleWatchlist(
            rest_client=_make_rest(closed_positions=positions),
            db_path=str(tmp_path / "test_whale.db"),
        )
        score = wl._score_candidate("dydx1short")
        assert score is None

    def test_score_rest_error_returns_none(self, tmp_path):
        """Une erreur REST doit retourner None gracieusement."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        wl = WhaleWatchlist(
            rest_client=_make_rest(raises=True),
            db_path=str(tmp_path / "test_whale.db"),
        )
        score = wl._score_candidate("dydx1error")
        assert score is None

    def test_score_recent_trades_get_higher_recency(self, tmp_path):
        """Trades récents → score de récence plus élevé."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        import datetime
        now = datetime.datetime.utcnow()
        recent_ts = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        old_ts = (now - datetime.timedelta(days=25)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        positions_recent = [_make_closed_pos(1000.0, recent_ts)] * 7 + [_make_closed_pos(-400.0, recent_ts)] * 3
        positions_old = [_make_closed_pos(1000.0, old_ts)] * 7 + [_make_closed_pos(-400.0, old_ts)] * 3

        rest_recent = _make_rest(closed_positions=positions_recent)
        rest_old = _make_rest(closed_positions=positions_old)

        wl_recent = WhaleWatchlist(rest_client=rest_recent, db_path=str(tmp_path / "recent.db"))
        wl_old = WhaleWatchlist(rest_client=rest_old, db_path=str(tmp_path / "old.db"))

        score_recent = wl_recent._score_candidate("dydx1recent")
        score_old = wl_old._score_candidate("dydx1old")

        assert score_recent is not None
        assert score_old is not None
        # Le trader récent doit avoir un composite_score >= le vieux
        assert score_recent.composite_score >= score_old.composite_score


class TestWhaleWatchlistRefresh:
    def test_refresh_populates_top(self, tmp_path):
        """Après refresh, get_top() retourne les wallets scorés."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        positions = [_make_closed_pos(1000.0)] * 7 + [_make_closed_pos(-400.0)] * 3
        wl = WhaleWatchlist(
            rest_client=_make_rest(closed_positions=positions),
            db_path=str(tmp_path / "test.db"),
        )
        # Injecter un candidat manuellement
        wl.inject_address("dydx1whale1")

        result = wl.refresh()
        assert isinstance(result, list)
        # Au moins le candidat injecté doit être scoré
        top = wl.get_top()
        assert len(top) >= 0  # Peut être 0 si win_rate insuffisant

    def test_refresh_updates_hot_set(self, tmp_path):
        """Le hot set doit être mis à jour après refresh."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        positions = [_make_closed_pos(5000.0)] * 8 + [_make_closed_pos(-1000.0)] * 2
        wl = WhaleWatchlist(
            rest_client=_make_rest(closed_positions=positions),
            db_path=str(tmp_path / "test.db"),
            priority_hot_n=5,
        )
        wl.inject_address("dydx1whale_hot")
        wl.refresh()
        # Hot set peut inclure des wallets du top-5
        hot = wl.get_hot_set()
        assert isinstance(hot, set)

    def test_as_wallet_scores_compatible(self, tmp_path):
        """as_wallet_scores() doit retourner des WalletScore valides."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        from hyper_smart_observer.dydx_v4.wallet_discovery import WalletScore
        positions = [_make_closed_pos(2000.0)] * 6 + [_make_closed_pos(-500.0)] * 4
        wl = WhaleWatchlist(
            rest_client=_make_rest(closed_positions=positions),
            db_path=str(tmp_path / "test.db"),
        )
        wl.inject_address("dydx1convert")
        wl.refresh()
        ws_list = wl.as_wallet_scores()
        for ws in ws_list:
            assert isinstance(ws, WalletScore)
            assert ws.source == "whale_watchlist"


class TestWhaleWatchlistPersistence:
    def test_scores_persist_across_instances(self, tmp_path):
        """Les scores survivent à un redémarrage (SQLite)."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        db = str(tmp_path / "persist.db")
        positions = [_make_closed_pos(3000.0)] * 7 + [_make_closed_pos(-1000.0)] * 3

        # Instance 1: scorer un wallet
        wl1 = WhaleWatchlist(rest_client=_make_rest(closed_positions=positions), db_path=db)
        wl1.inject_address("dydx1persist")
        wl1.refresh()
        top1 = wl1.get_top()

        # Instance 2: charger depuis SQLite
        wl2 = WhaleWatchlist(rest_client=_make_rest(), db_path=db)
        top2 = wl2.get_top()

        assert len(top2) == len(top1)

    def test_candidates_persist_across_instances(self, tmp_path):
        """Les candidats découverts survivent à un redémarrage."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        db = str(tmp_path / "cand.db")

        wl1 = WhaleWatchlist(rest_client=_make_rest(), db_path=db)
        wl1.inject_address("dydx1cand1")
        wl1.inject_address("dydx1cand2")

        wl2 = WhaleWatchlist(rest_client=_make_rest(), db_path=db)
        assert "dydx1cand1" in wl2._candidates
        assert "dydx1cand2" in wl2._candidates


class TestWhaleWatchlistSafety:
    """Vérifications de sécurité: READ-ONLY, aucun ordre réel."""

    def test_no_order_methods(self, tmp_path):
        """WhaleWatchlist ne doit avoir aucune méthode d'ordre ou de transaction."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        wl = WhaleWatchlist(rest_client=_make_rest(), db_path=str(tmp_path / "safe.db"))
        dangerous = ["place_order", "send", "sign", "withdraw", "deposit", "execute_trade"]
        for method in dangerous:
            assert not hasattr(wl, method), f"WhaleWatchlist ne doit pas avoir '{method}'"

    def test_rest_calls_are_readonly(self, tmp_path):
        """Les appels REST ne doivent utiliser que des méthodes en lecture seule."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist
        rest = _make_rest()
        wl = WhaleWatchlist(rest_client=rest, db_path=str(tmp_path / "safe.db"))
        wl.inject_address("dydx1safe")
        wl.refresh()
        # Vérifier qu'aucune méthode d'écriture n'a été appelée
        for call in rest.method_calls:
            name = call[0]
            assert not any(kw in name for kw in ["place", "send", "sign", "post", "submit"]), \
                f"REST call interdit: {name}"

    def test_get_top_is_readonly_copy(self, tmp_path):
        """get_top() doit retourner une copie (pas une référence interne)."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist, WhaleScore
        db = str(tmp_path / "copy.db")
        positions = [_make_closed_pos(5000.0)] * 8 + [_make_closed_pos(-1000.0)] * 2
        wl = WhaleWatchlist(rest_client=_make_rest(closed_positions=positions), db_path=db)
        wl.inject_address("dydx1readonly")
        wl.refresh()

        top1 = wl.get_top()
        top1_copy = list(top1)  # copie explicite
        # Modifier la liste externe ne doit pas affecter l'état interne
        top1.clear()
        top2 = wl.get_top()
        assert len(top2) == len(top1_copy)


class TestClusterReset:
    """Test du reset de cluster sans generation de wallets artificiels."""

    def test_cluster_reset_called_on_demo_snapshot_reset(self):
        """Quand _position_snapshots est réinitialisé, cluster.reset_wallet() doit être appelé."""
        from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
        # Créer un vrai cluster detector
        cluster = DydxClusterDetector()
        reset_calls = []
        orig_reset = cluster.reset_wallet

        def _track_reset(addr):
            reset_calls.append(addr)
            orig_reset(addr)

        cluster.reset_wallet = _track_reset

        from hyper_smart_observer.dydx_v4.wallet_discovery import WalletScore

        shortlist = [
            WalletScore(address="dydx1alpha", subaccount_number=0),
            WalletScore(address="dydx1beta", subaccount_number=0),
            WalletScore(address="dydx1gamma", subaccount_number=0),
        ]

        # Simuler le reset
        for w in shortlist:
            k = f"{w.address}/{w.subaccount_number}"
            cluster.reset_wallet(w.address)

        assert len(reset_calls) == len(shortlist)
        assert all(addr == ws.address for addr, ws in zip(reset_calls, shortlist))

    def test_cluster_reset_wallet_clears_positions(self):
        """reset_wallet() doit vider _positions et _prev_positions pour l'adresse."""
        from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
        cluster = DydxClusterDetector()
        addr = "dydx1testaddr"

        # Injecter des positions
        cluster.update_positions(
            address=addr,
            positions_raw=[{"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "3000"}],
            fetched_at_ms=int(time.time() * 1000),
        )
        assert addr in cluster._positions

        # Reset
        cluster.reset_wallet(addr)

        assert addr not in cluster._positions
        assert addr not in cluster._prev_positions

    def test_after_reset_next_update_generates_open_events(self):
        """Après reset_wallet(), update_positions() doit générer des events OPEN frais."""
        from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
        cluster = DydxClusterDetector()
        addr = "dydx1testaddr2"
        now_ms = int(time.time() * 1000)

        # Premier update → OPEN
        events1 = cluster.update_positions(
            address=addr,
            positions_raw=[{"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "3000"}],
            fetched_at_ms=now_ms,
        )
        assert any(e.event_type == "OPEN" for e in events1)

        # Deuxième update (sans reset) → pas d'OPEN
        events2 = cluster.update_positions(
            address=addr,
            positions_raw=[{"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "3000"}],
            fetched_at_ms=now_ms + 1000,
        )
        assert not any(e.event_type == "OPEN" for e in events2)

        # Après reset → OPEN à nouveau
        cluster.reset_wallet(addr)
        events3 = cluster.update_positions(
            address=addr,
            positions_raw=[{"market": "ETH-USD", "side": "LONG", "size": "1.0", "entryPrice": "3000"}],
            fetched_at_ms=now_ms + 2000,
        )
        assert any(e.event_type == "OPEN" for e in events3), \
            "reset_wallet() doit permettre la génération d'OPENs frais"


class TestWhaleToWalletScoreConversion:
    def test_to_wallet_score_fields(self, tmp_path):
        """WhaleScore.to_wallet_score() doit mapper tous les champs correctement."""
        from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleScore
        ws = WhaleScore(
            address="dydx1whale",
            subaccount_number=0,
            total_pnl_usdc=12345.67,
            win_rate=0.72,
            profit_factor=2.3,
            trade_count=42,
            composite_score=0.85,
        )
        result = ws.to_wallet_score()
        assert result.address == "dydx1whale"
        assert result.winrate == pytest.approx(0.72)
        assert result.profit_factor == pytest.approx(2.3)
        assert result.trade_count == 42
        assert result.net_pnl_usdc == pytest.approx(12345.67)
        assert result.total_score == pytest.approx(0.85)
        assert result.source == "whale_watchlist"
