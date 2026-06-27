from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hyper_smart_observer.dydx_v4.leaderboard_import import read_leaderboard_file
from hyper_smart_observer.dydx_v4.whale_ranker import whale_score

DEFAULT_WHALE_FILE = "data/import/dydx_whales.csv"


class WalletRow:
    def __init__(self, address: str, metrics: dict[str, Any]) -> None:
        self.address = address
        self.net_pnl_usdc = metrics.get("net_pnl_usdc")
        self.roi_pct = metrics.get("roi_pct")
        self.winrate = metrics.get("winrate")
        self.profit_factor = metrics.get("profit_factor")
        self.trade_count = metrics.get("trade_count")
        self.usdc_balance = metrics.get("usdc_balance")
        self.activity_count = metrics.get("activity_count") or metrics.get("pnl_ticks") or metrics.get("open_positions") or 0
        self.open_positions = metrics.get("open_positions")
        self.markets = metrics.get("markets")


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def replay_whale_file(path: str | Path = DEFAULT_WHALE_FILE, limit: int = 100) -> dict[str, Any]:
    rows = [WalletRow(addr, metrics) for addr, metrics in read_leaderboard_file(path)]
    ranked = sorted(rows, key=lambda w: (whale_score(w), _num(w.net_pnl_usdc), _num(w.usdc_balance)), reverse=True)
    selected = ranked[: max(0, limit)]
    total_pnl = sum(_num(w.net_pnl_usdc) for w in selected)
    positive = sum(1 for w in selected if _num(w.net_pnl_usdc) > 0)
    markets: dict[str, int] = {}
    for w in selected:
        for market in str(w.markets or "").split(";"):
            market = market.strip()
            if market:
                markets[market] = markets.get(market, 0) + 1
    return {
        "path": str(path),
        "wallets_loaded": len(rows),
        "wallets_selected": len(selected),
        "positive_pnl_wallets": positive,
        "selected_total_pnl_usdc": round(total_pnl, 6),
        "top_markets": dict(sorted(markets.items(), key=lambda x: x[1], reverse=True)[:20]),
        "top_wallets": [
            {
                "address": w.address,
                "whale_score": whale_score(w),
                "net_pnl_usdc": _num(w.net_pnl_usdc),
                "usdc_balance": _num(w.usdc_balance),
                "open_positions": _num(w.open_positions),
                "markets": w.markets,
            }
            for w in selected[:25]
        ],
        "read_only": True,
        "paper_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay/analyze local dYdX whale import file")
    parser.add_argument("--path", default=DEFAULT_WHALE_FILE)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(replay_whale_file(args.path, args.limit), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["DEFAULT_WHALE_FILE", "replay_whale_file"]
