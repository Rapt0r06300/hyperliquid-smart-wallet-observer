from __future__ import annotations

from collections.abc import Mapping, Sequence

from hl_observer.hyperliquid.schemas import WalletProfile, WalletStyle


def profile_from_metrics(address: str, metrics: dict[str, float]) -> WalletProfile:
    return WalletProfile(
        address=address,
        trades_count=int(metrics.get("trades_count", 0)),
        active_days=int(metrics.get("active_days", 0)),
        pnl_bps=metrics.get("pnl_bps", 0.0),
        win_rate=metrics.get("win_rate", 0.0),
        profit_factor=metrics.get("profit_factor", 0.0),
        max_drawdown_bps=metrics.get("max_drawdown_bps", 0.0),
        top_trade_pnl_share=metrics.get("top_trade_pnl_share", 0.0),
        toxicity_score=metrics.get("toxicity_score", 0.0),
        style=WalletStyle(metrics.get("style", WalletStyle.UNKNOWN.value)),
    )


def lookahead_filter_receipt(*, selected_at_ms: int, fills: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Keep only fills observed at or before selection; reject missing timestamps."""
    if isinstance(selected_at_ms, bool) or not isinstance(selected_at_ms, int):
        return {"status": "UNMEASURABLE", "reason": "selected_at_ms_must_be_integer"}
    observed: list[Mapping[str, object]] = []
    removed = 0
    for fill in fills:
        if not isinstance(fill, Mapping):
            return {"status": "UNMEASURABLE", "reason": "fill_must_be_mapping"}
        timestamp = next((fill.get(key) for key in ("timestamp_ms", "time", "timestamp", "ts") if key in fill), None)
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            return {"status": "UNMEASURABLE", "reason": "fill_timestamp_missing_or_invalid"}
        if timestamp <= selected_at_ms:
            observed.append(fill)
        else:
            removed += 1
    return {
        "status": "PROVEN",
        "selected_at_ms": selected_at_ms,
        "observed_fills": tuple(observed),
        "observed_count": len(observed),
        "post_selection_removed": removed,
        "lookahead_free": True,
    }
