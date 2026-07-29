"""Reproducible runtime proof for the side-specific executable L2 walk."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from hl_observer.paper_trading.exec_model import simulate_depth_execution
from hl_observer.simulation.orderbook_execution_simulator import (
    simulate_orderbook_execution,
)


def run_audit() -> dict[str, object]:
    buy = simulate_depth_execution(
        side="BUY",
        notional_usdc=152.0,
        mid_price=100.0,
        asks=((101.0, 1.0), (102.0, 1.0)),
        bids=((1.0, 1_000_000.0),),
        min_fill_ratio=1.0,
    )
    sell = simulate_depth_execution(
        side="SELL",
        notional_usdc=149.0,
        mid_price=100.0,
        asks=((1_000.0, 1_000.0),),
        bids=((99.0, 1.0), (100.0, 0.5)),
        min_fill_ratio=1.0,
    )
    partial = simulate_depth_execution(
        side="BUY",
        notional_usdc=500.0,
        mid_price=100.0,
        asks=((101.0, 1.0),),
        bids=((99.0, 1_000.0),),
        min_fill_ratio=0.0,
    )
    adapter = simulate_orderbook_execution(
        side="BUY",
        notional_usdc=152.0,
        mid_price=100.0,
        asks=((101.0, 1.0), (102.0, 1.0)),
        bids=((1.0, 1_000_000.0),),
        min_fill_ratio=1.0,
    )
    checks = {
        "buy_uses_asks": tuple(level.price for level in buy.level_fills)
        == (101.0, 102.0),
        "sell_uses_bids": tuple(level.price for level in sell.level_fills)
        == (100.0, 99.0),
        "buy_vwap_exact": abs((buy.average_fill_price or 0.0) - (152.0 / 1.5))
        < 1e-8,
        "partial_not_invented": partial.filled_notional_usdc == 101.0
        and partial.missed_notional_usdc == 399.0
        and partial.partial,
        "legacy_adapter_parity": adapter.average_fill_price
        == buy.average_fill_price
        and adapter.filled_notional_usdc == buy.filled_notional_usdc
        and adapter.slippage_bps == buy.slippage_bps,
    }
    return {
        "audit": "executable_book_walk",
        "passed": all(checks.values()),
        "checks": checks,
        "buy": asdict(buy),
        "sell": asdict(sell),
        "partial": asdict(partial),
        "legacy_adapter": asdict(adapter),
        "paper_only": True,
        "real_execution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run_audit()
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
