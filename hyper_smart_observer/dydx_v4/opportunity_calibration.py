from __future__ import annotations

from dataclasses import replace
from typing import Any


def apply_opportunity_calibration(cfg: Any) -> Any:
    """Apply a high-recall paper-only profile without disabling safety gates."""
    return replace(
        cfg,
        max_signal_age_ms=max(int(getattr(cfg, "max_signal_age_ms", 0) or 0), 90_000),
        hard_max_signal_age_ms=max(int(getattr(cfg, "hard_max_signal_age_ms", 0) or 0), 90_000),
        min_edge_bps=min(float(getattr(cfg, "min_edge_bps", 3.0) or 3.0), 2.2),
        edge_safety_multiplier=min(float(getattr(cfg, "edge_safety_multiplier", 1.0) or 1.0), 1.0),
        consensus_min_wallets=max(2, int(getattr(cfg, "consensus_min_wallets", 2) or 2)),
        consensus_window_ms=max(int(getattr(cfg, "consensus_window_ms", 0) or 0), 5 * 60 * 1000),
        consensus_recency_bonus_window_ms=max(int(getattr(cfg, "consensus_recency_bonus_window_ms", 0) or 0), 45_000),
        consensus_recency_edge_multiplier=max(float(getattr(cfg, "consensus_recency_edge_multiplier", 1.0) or 1.0), 1.08),
        confluence_window_ms=max(int(getattr(cfg, "confluence_window_ms", 0) or 0), 45_000),
        confluence_edge_multiplier=max(float(getattr(cfg, "confluence_edge_multiplier", 1.0) or 1.0), 1.12),
        fast_scanner_enabled=True,
        fast_scanner_hot_capacity=max(int(getattr(cfg, "fast_scanner_hot_capacity", 0) or 0), 2500),
        max_decision_wallets=max(int(getattr(cfg, "max_decision_wallets", 0) or 0), 3000),
        rest_poll_cap=max(int(getattr(cfg, "rest_poll_cap", 0) or 0), 250),
        market_context_ttl_s=min(float(getattr(cfg, "market_context_ttl_s", 60.0) or 60.0), 20.0),
        stream_window_ms=max(int(getattr(cfg, "stream_window_ms", 0) or 0), 12_000),
        market_flow_min_volume_usdc=min(float(getattr(cfg, "market_flow_min_volume_usdc", 10_000.0) or 10_000.0), 7_500.0),
        market_flow_min_imbalance=min(float(getattr(cfg, "market_flow_min_imbalance", 0.65) or 0.65), 0.60),
        flow_min_trades=min(int(getattr(cfg, "flow_min_trades", 5) or 5), 3),
        max_spread_bps=max(float(getattr(cfg, "max_spread_bps", 40.0) or 40.0), 45.0),
        min_hold_seconds=min(float(getattr(cfg, "min_hold_seconds", 30.0) or 30.0), 20.0),
        reopen_cooldown_seconds=min(float(getattr(cfg, "reopen_cooldown_seconds", 15.0) or 15.0), 8.0),
        scalper_min_hold_seconds=min(float(getattr(cfg, "scalper_min_hold_seconds", 60.0) or 60.0), 45.0),
        max_open_paper_trades=max(int(getattr(cfg, "max_open_paper_trades", 25) or 25), 30),
        partial_tp_enabled=True,
        breakeven_stop_enabled=True,
    )


def calibration_summary(cfg: Any) -> dict:
    return {
        "max_signal_age_ms": int(getattr(cfg, "max_signal_age_ms", 0) or 0),
        "min_edge_bps": float(getattr(cfg, "min_edge_bps", 0.0) or 0.0),
        "fast_scanner_hot_capacity": int(getattr(cfg, "fast_scanner_hot_capacity", 0) or 0),
        "max_decision_wallets": int(getattr(cfg, "max_decision_wallets", 0) or 0),
        "rest_poll_cap": int(getattr(cfg, "rest_poll_cap", 0) or 0),
        "consensus_window_ms": int(getattr(cfg, "consensus_window_ms", 0) or 0),
        "confluence_window_ms": int(getattr(cfg, "confluence_window_ms", 0) or 0),
        "market_context_ttl_s": float(getattr(cfg, "market_context_ttl_s", 0.0) or 0.0),
        "read_only": bool(getattr(cfg, "read_only", True)),
        "paper_only": bool(getattr(cfg, "paper_only", True)),
    }


__all__ = ["apply_opportunity_calibration", "calibration_summary"]
