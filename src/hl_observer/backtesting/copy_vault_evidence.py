"""Presentation helpers for Copy-Vault executable walk-forward evidence."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def temporal_evidence(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    """Project an evaluation into the canonical temporal proof payload."""

    segments = evaluation.get("segments") if isinstance(evaluation.get("segments"), Mapping) else {}
    oos_summary = (segments.get("oos") or {}).get("summary") or {}
    forward_summary = (segments.get("forward") or {}).get("summary") or {}
    placebo_summary = (evaluation.get("placebo_inverted_oos") or {}).get("summary") or {}
    oos_count = int(oos_summary.get("positions_fermees") or 0)
    forward_count = int(forward_summary.get("positions_fermees") or 0)
    placebo_count = int(placebo_summary.get("positions_fermees") or 0)
    oos_net = oos_summary.get("net_pnl_usd") if oos_count > 0 else None
    placebo_net = placebo_summary.get("net_pnl_usd") if placebo_count > 0 else None
    forward_trades = (
        (evaluation.get("trades") or {}).get("forward") or []
        if isinstance(evaluation.get("trades"), Mapping) else []
    )
    causal_forward = bool(forward_trades) and all(
        row.get("causal_forward_eligible") is True for row in forward_trades
    )

    def proof_segment(summary: Mapping[str, Any], *, count: int) -> dict[str, Any]:
        return {key: summary.get(key) for key in (
            "gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd",
            "latency_cost_usd", "net_pnl_usd", "trade_ids_count", "trade_ids_sha256",
            "duplicate_trade_ids",
        )} | {"sample_count": count, "liquidatable_net": summary.get("LIQUIDATABLE_NET") is True}

    return {
        "oos": {**proof_segment(oos_summary, count=oos_count), "no_lookahead": True, "purged": True},
        "forward": {
            **proof_segment(forward_summary, count=forward_count),
            "post_freeze": causal_forward, "causal_live_only": causal_forward,
        },
        "placebos": {
            "beaten": oos_net is not None and placebo_net is not None and float(oos_net) > float(placebo_net),
            "candidate_net_usd": oos_net, "placebo_net_usd": placebo_net,
            "method": "same_metaorders_inverted_direction",
        },
    }


__all__ = ["temporal_evidence"]
