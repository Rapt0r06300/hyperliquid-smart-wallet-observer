from __future__ import annotations

from dataclasses import replace
from typing import Any


REAL_FLOW_MIN_VOLUME_USDC = 2_500.0
REAL_FLOW_MIN_IMBALANCE = 0.54
REAL_FLOW_MIN_TRADES = 2


def apply_real_flow_calibration(cfg: Any) -> Any:
    return replace(
        cfg,
        market_flow_enabled=True,
        market_flow_min_volume_usdc=min(float(getattr(cfg, "market_flow_min_volume_usdc", 10_000.0) or 10_000.0), REAL_FLOW_MIN_VOLUME_USDC),
        market_flow_min_imbalance=min(float(getattr(cfg, "market_flow_min_imbalance", 0.65) or 0.65), REAL_FLOW_MIN_IMBALANCE),
        flow_min_trades=min(int(getattr(cfg, "flow_min_trades", 5) or 5), REAL_FLOW_MIN_TRADES),
        allow_market_flow_solo_entries=False,
    )


def real_flow_summary(cfg: Any) -> dict[str, Any]:
    return {
        "market_flow_enabled": bool(getattr(cfg, "market_flow_enabled", False)),
        "market_flow_min_volume_usdc": float(getattr(cfg, "market_flow_min_volume_usdc", 0.0) or 0.0),
        "market_flow_min_imbalance": float(getattr(cfg, "market_flow_min_imbalance", 0.0) or 0.0),
        "flow_min_trades": int(getattr(cfg, "flow_min_trades", 0) or 0),
        "allow_market_flow_solo_entries": bool(getattr(cfg, "allow_market_flow_solo_entries", False)),
        "source": "REAL_PUBLIC_DYDX_TRADES",
        "read_only": True,
        "paper_only": True,
    }


__all__ = [
    "REAL_FLOW_MIN_VOLUME_USDC",
    "REAL_FLOW_MIN_IMBALANCE",
    "REAL_FLOW_MIN_TRADES",
    "apply_real_flow_calibration",
    "real_flow_summary",
]
