"""
Tests de sécurité et configuration dYdX v4.

Tests obligatoires:
- config safe par défaut
- aucun ordre réel possible
- aucun appel trading privé
- aucune clé requise
"""

from __future__ import annotations

import pytest

from hyper_smart_observer.dydx_v4.config import DydxV4Config, DydxNetwork, load_config_from_env
from hyper_smart_observer.dydx_v4.safety import (
    audit_config,
    assert_paper_only,
    assert_no_private_key,
    check_url_safety,
    check_payload_safety,
    gate_signal_for_live,
)


class TestDefaultConfig:
    """La config par défaut doit être sûre."""

    def test_paper_only_is_true_by_default(self):
        cfg = DydxV4Config()
        assert cfg.paper_only is True

    def test_read_only_is_true_by_default(self):
        cfg = DydxV4Config()
        assert cfg.read_only is True

    def test_allow_trading_is_false_by_default(self):
        cfg = DydxV4Config()
        assert cfg.allow_trading is False

    def test_allow_private_key_is_false_by_default(self):
        cfg = DydxV4Config()
        assert cfg.allow_private_key is False

    def test_network_is_mainnet_by_default(self):
        # MAINNET par défaut depuis migration (TESTNET n'a aucune activité → 0 wallets)
        cfg = DydxV4Config()
        assert cfg.network == DydxNetwork.MAINNET

    def test_enabled_is_false_by_default(self):
        cfg = DydxV4Config()
        assert cfg.enabled is False

    def test_max_signal_age_ms(self):
        cfg = DydxV4Config()
        assert cfg.max_signal_age_ms == 30000  # aligné avec edge_calculator half-life
        assert cfg.hard_max_signal_age_ms == 30000

    def test_min_edge_bps(self):
        cfg = DydxV4Config()
        assert cfg.min_edge_bps >= 3.0  # recalibré: filtre le bruit, pas les modestes

    def test_starting_balance(self):
        cfg = DydxV4Config()
        assert cfg.starting_balance_usdc == 1000.0

    def test_max_open_paper_trades(self):
        cfg = DydxV4Config()
        assert cfg.max_open_paper_trades == 25  # env override ignored (safety)

    def test_trend_regime_and_dynamic_sizing_defaults(self):
        cfg = DydxV4Config()
        assert cfg.trend_filter_enabled is True
        assert cfg.regime_detector_enabled is True
        assert cfg.dynamic_sizing_enabled is True
        assert cfg.paper_notional_min_usdc == 20.0
        assert cfg.paper_notional_base_usdc == 75.0
        assert cfg.paper_notional_max_usdc == 100.0
        assert cfg.volume_spike_enabled is True
        assert cfg.correlation_gate_enabled is True
        assert cfg.confluence_enabled is True
        assert cfg.consensus_window_ms == 3 * 60 * 1000
        assert cfg.consensus_recency_bonus_window_ms == 30_000
        assert cfg.funding_edge_enabled is True
        assert cfg.funding_edge_horizon_hours == 1.0
        assert cfg.decision_log_enabled is True
        assert cfg.decision_log_path.endswith("decisions.jsonl")
        assert cfg.partial_tp_enabled is True
        assert cfg.partial_tp_fraction == 0.50
        assert cfg.partial_tp2_multiplier == 2.0


class TestSafetyViolations:
    """Les configurations dangereuses doivent lever des erreurs."""

    def test_allow_trading_raises(self):
        with pytest.raises(ValueError, match="allow_trading"):
            DydxV4Config(allow_trading=True, paper_only=True)

    def test_allow_private_key_raises(self):
        with pytest.raises(ValueError, match="allow_private_key"):
            DydxV4Config(allow_private_key=True)

    def test_paper_only_false_raises(self):
        with pytest.raises(ValueError, match="paper_only"):
            DydxV4Config(paper_only=False)

    def test_read_only_false_raises(self):
        with pytest.raises(ValueError, match="read_only"):
            DydxV4Config(read_only=False)

    def test_mainnet_with_require_testnet_raises(self):
        with pytest.raises(ValueError, match="require_testnet"):
            DydxV4Config(
                require_testnet=True,
                network=DydxNetwork.MAINNET,
            )


class TestAssertPaperOnly:
    def test_paper_only_passes(self):
        cfg = DydxV4Config()
        # Ne doit pas lever
        assert_paper_only(cfg)

    def test_paper_only_fails_if_trading_somehow_enabled(self):
        """Tester directement la gate, même si le constructeur bloque déjà."""
        cfg = DydxV4Config()
        object.__setattr__(cfg, "allow_trading", True)
        with pytest.raises(RuntimeError, match="allow_trading"):
            assert_paper_only(cfg)


class TestUrlSafety:
    def test_safe_url_passes(self):
        result = check_url_safety("https://indexer.v4testnet.dydx.exchange/v4/markets")
        assert result.allowed is True

    def test_private_key_in_url_blocked(self):
        result = check_url_safety("https://example.com/private_key/sign")
        assert result.allowed is False
        assert "FORBIDDEN" in result.reason

    def test_orders_url_blocked(self):
        result = check_url_safety("https://example.com/v4/orders")
        assert result.allowed is False

    def test_withdraw_url_blocked(self):
        result = check_url_safety("https://example.com/withdrawals")
        assert result.allowed is False


class TestPayloadSafety:
    def test_safe_payload_passes(self):
        result = check_payload_safety({"market": "BTC-USD", "limit": 100})
        assert result.allowed is True

    def test_private_key_in_payload_blocked(self):
        result = check_payload_safety({"private_key": "0xdeadbeef"})
        assert result.allowed is False

    def test_mnemonic_in_payload_blocked(self):
        result = check_payload_safety({"mnemonic": "word1 word2 word3"})
        assert result.allowed is False


class TestSignalGate:
    def test_fresh_signal_passes(self):
        cfg = DydxV4Config()
        result = gate_signal_for_live(
            config=cfg,
            signal_age_ms=1000,
            account_address="0xabc123",
            market="BTC-USD",
            edge_remaining_bps=100.0,
            total_cost_bps=20.0,
        )
        assert result.allowed is True

    def test_stale_signal_blocked(self):
        cfg = DydxV4Config()
        result = gate_signal_for_live(
            config=cfg,
            signal_age_ms=35000,  # > 30000ms hard_max
            account_address="0xabc123",
            market="BTC-USD",
            edge_remaining_bps=100.0,
            total_cost_bps=20.0,
        )
        assert result.allowed is False
        assert "STALE" in result.reason

    def test_test_fixture_account_blocked(self):
        cfg = DydxV4Config()
        result = gate_signal_for_live(
            config=cfg,
            signal_age_ms=1000,
            account_address="0x1111111111111111111111111111111111111111",
            market="BTC-USD",
            edge_remaining_bps=100.0,
            total_cost_bps=20.0,
        )
        assert result.allowed is False
        assert "TEST_FIXTURE" in result.reason

    def test_unknown_market_blocked(self):
        cfg = DydxV4Config()
        result = gate_signal_for_live(
            config=cfg,
            signal_age_ms=1000,
            account_address="0xabc123",
            market="FAKECOIN-USD",  # pas dans la whitelist
            edge_remaining_bps=100.0,
            total_cost_bps=20.0,
        )
        assert result.allowed is False
        assert "MARKET_NOT_WHITELISTED" in result.reason

    def test_negative_edge_blocked(self):
        cfg = DydxV4Config()
        result = gate_signal_for_live(
            config=cfg,
            signal_age_ms=1000,
            account_address="0xabc123",
            market="BTC-USD",
            edge_remaining_bps=-5.0,
            total_cost_bps=20.0,
        )
        assert result.allowed is False
        assert "EDGE" in result.reason

    def test_edge_too_low_blocked(self):
        cfg = DydxV4Config()
        result = gate_signal_for_live(
            config=cfg,
            signal_age_ms=1000,
            account_address="0xabc123",
            market="BTC-USD",
            edge_remaining_bps=1.5,  # < 3 bps min (recalibré)
            total_cost_bps=1.0,
        )
        assert result.allowed is False
        assert "EDGE" in result.reason

    def test_cost_multiplier_blocked(self):
        """Edge doit être > 1.2x total_cost_bps (recalibré)."""
        cfg = DydxV4Config()
        result = gate_signal_for_live(
            config=cfg,
            signal_age_ms=1000,
            account_address="0xabc123",
            market="BTC-USD",
            edge_remaining_bps=18.0,   # > 3 mais < 1.0x*20=20
            total_cost_bps=20.0,
        )
        assert result.allowed is False


class TestAuditConfig:
    def test_safe_config_no_issues(self):
        cfg = DydxV4Config()
        issues = audit_config(cfg)
        critical = [i for i in issues if "CRITICAL" in i]
        assert len(critical) == 0

    def test_env_config_always_safe(self, monkeypatch):
        """load_config_from_env ne peut jamais activer allow_trading."""
        monkeypatch.setenv("DYDX_ALLOW_TRADING", "true")
        cfg = load_config_from_env()
        assert cfg.allow_trading is False
        assert cfg.paper_only is True

    def test_env_config_loads_trend_regime_and_sizing(self, monkeypatch):
        monkeypatch.setenv("DYDX_TREND_FILTER", "0")
        monkeypatch.setenv("DYDX_REGIME_DETECTOR", "0")
        monkeypatch.setenv("DYDX_DYNAMIC_SIZING", "1")
        monkeypatch.setenv("DYDX_PAPER_NOTIONAL_MIN_USDC", "25")
        monkeypatch.setenv("DYDX_PAPER_NOTIONAL_BASE_USDC", "55")
        monkeypatch.setenv("DYDX_PAPER_NOTIONAL_MAX_USDC", "95")
        monkeypatch.setenv("DYDX_CHOPPY_EFFICIENCY_MAX", "0.22")
        monkeypatch.setenv("DYDX_VOLUME_SPIKE_ZSCORE_MIN", "2.5")
        monkeypatch.setenv("DYDX_CORRELATION_GATE", "0")
        monkeypatch.setenv("DYDX_MAX_CORRELATED_SAME_SIDE", "2")
        monkeypatch.setenv("DYDX_CONFLUENCE_WINDOW_MS", "15000")
        monkeypatch.setenv("DYDX_CONSENSUS_RECENCY_BONUS_WINDOW_MS", "12000")
        monkeypatch.setenv("DYDX_CONSENSUS_RECENCY_EDGE_MULTIPLIER", "1.09")
        monkeypatch.setenv("DYDX_FUNDING_EDGE", "0")
        monkeypatch.setenv("DYDX_FUNDING_EDGE_HORIZON_HOURS", "2.5")
        monkeypatch.setenv("DYDX_DECISION_LOG", "0")
        monkeypatch.setenv("DYDX_DECISION_LOG_PATH", "logs/custom_decisions.jsonl")
        monkeypatch.setenv("DYDX_PARTIAL_TP", "0")
        monkeypatch.setenv("DYDX_PARTIAL_TP_FRACTION", "0.4")
        monkeypatch.setenv("DYDX_PARTIAL_TP2_MULTIPLIER", "2.5")
        cfg = load_config_from_env()
        assert cfg.trend_filter_enabled is False
        assert cfg.regime_detector_enabled is False
        assert cfg.dynamic_sizing_enabled is True
        assert cfg.paper_notional_min_usdc == 25.0
        assert cfg.paper_notional_base_usdc == 55.0
        assert cfg.paper_notional_max_usdc == 95.0
        assert cfg.choppy_efficiency_max == 0.22
        assert cfg.volume_spike_zscore_min == 2.5
        assert cfg.correlation_gate_enabled is False
        assert cfg.consensus_recency_bonus_window_ms == 12000
        assert cfg.consensus_recency_edge_multiplier == 1.09
        assert cfg.funding_edge_enabled is False
        assert cfg.funding_edge_horizon_hours == 2.5
        assert cfg.decision_log_enabled is False
        assert cfg.decision_log_path == "logs/custom_decisions.jsonl"
        assert cfg.partial_tp_enabled is False
        assert cfg.partial_tp_fraction == 0.4
        assert cfg.partial_tp2_multiplier == 2.5
        assert cfg.max_correlated_same_side == 2  # env override
        assert cfg.confluence_window_ms == 15000
        assert cfg.allow_trading is False
        assert cfg.allow_private_key is False
