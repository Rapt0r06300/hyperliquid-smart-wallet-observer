"""V13 — Canonical decision-time feature set (single source of truth).

Used by BOTH the offline training-row builder and the live inference path so the model's
feature names always align. Decision-time only (no-lookahead): nothing here may depend on
the outcome. Pure / numeric.
"""

from __future__ import annotations


def canonical_feature_names() -> list[str]:
    return [
        "net_edge_bps", "signal_age_ms", "consensus_wallets", "liquidity_score",
        "bias_bps", "whale_strength", "leader_score", "adverse_move_bps", "price_deviation_bps",
    ]


def canonical_features(
    *,
    net_edge_bps: float = 0.0,
    signal_age_ms: float = 0.0,
    consensus_wallets: float = 0.0,
    liquidity_score: float = 0.0,
    bias_bps: float = 0.0,
    whale_strength: float = 0.0,
    leader_score: float = 0.0,
    adverse_move_bps: float = 0.0,
    price_deviation_bps: float = 0.0,
) -> dict:
    return {
        "net_edge_bps": float(net_edge_bps),
        "signal_age_ms": float(signal_age_ms),
        "consensus_wallets": float(consensus_wallets),
        "liquidity_score": float(liquidity_score),
        "bias_bps": float(bias_bps),
        "whale_strength": float(whale_strength),
        "leader_score": float(leader_score),
        "adverse_move_bps": float(adverse_move_bps),
        "price_deviation_bps": float(price_deviation_bps),
    }


__all__ = ["canonical_feature_names", "canonical_features"]
