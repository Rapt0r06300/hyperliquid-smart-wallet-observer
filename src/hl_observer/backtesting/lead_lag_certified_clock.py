"""Certified Lead-Lag economic entrypoint without global monkeypatching."""
from __future__ import annotations

from typing import Any

from hl_observer.backtesting import lead_lag_shadow
from hl_observer.backtesting.lead_lag_certified_backtest import (
    CERTIFIED_TIMESTAMP_POLICY,
    backtest_certified,
    certified_event_time_ns,
    load_certified_tape,
    partition_universe,
)


def backtest_with_certified_wall_clock(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the canonical economic path on restart-safe wall timestamps only."""
    return backtest_certified(*args, **kwargs)


def certified_protocol_signature() -> dict[str, Any]:
    signature = dict(lead_lag_shadow.walk_forward_protocol_signature())
    signature["timestamp_clock"] = CERTIFIED_TIMESTAMP_POLICY
    signature["monotonic_only_rows_eligible_for_economic_proof"] = False
    signature["certified_loader"] = (
        "hl_observer.backtesting.lead_lag_certified_backtest:load_certified_tape"
    )
    signature["global_clock_monkeypatch"] = False
    return signature


__all__ = [
    "CERTIFIED_TIMESTAMP_POLICY",
    "backtest_with_certified_wall_clock",
    "certified_event_time_ns",
    "certified_protocol_signature",
    "load_certified_tape",
    "partition_universe",
]
