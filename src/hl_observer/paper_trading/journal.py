"""Paper trade journal (V12, repos 03/08): append-only record of paper trades.

Records opens/adds/reduces/closes with the realized net PnL at the real mark (PnL is passed
in, never invented). Pure in-memory; JSON-safe rows for the dashboard/exports. No order.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PaperTradeJournal:
    _rows: list[dict] = field(default_factory=list)

    def record(self, *, kind: str, coin: str, side: str, notional_usdt: float = 0.0,
               price: float | None = None, realized_net_pnl_usdc: float | None = None,
               reason: str | None = None, now_ms: int | None = None) -> dict:
        row = {
            "kind": str(kind).upper(),                 # OPEN/ADD/REDUCE/CLOSE
            "coin": str(coin).upper(),
            "side": str(side).upper(),
            "notional_usdt": round(float(notional_usdt), 6),
            "price": price,
            "realized_net_pnl_usdc": (None if realized_net_pnl_usdc is None
                                      else round(float(realized_net_pnl_usdc), 6)),
            "reason": reason,
            "recorded_at_ms": None if now_ms is None else int(now_ms),
            "not_an_order": True,
            "simulation_only": True,
        }
        self._rows.append(row)
        return row

    def rows(self) -> list[dict]:
        return list(self._rows)

    def summary(self) -> dict:
        realized = sum(r["realized_net_pnl_usdc"] or 0.0 for r in self._rows)
        closes = [r for r in self._rows if r["kind"] == "CLOSE"]
        wins = sum(1 for r in closes if (r["realized_net_pnl_usdc"] or 0.0) > 0)
        return {
            "trades": len(self._rows),
            "closes": len(closes),
            "winning_closes": wins,
            "realized_net_pnl_usdc": round(realized, 6),
            "empty": not self._rows,
        }


__all__ = ["PaperTradeJournal"]
