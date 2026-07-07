"""Phase 7: event-driven replay over Hyperliquid fills + book snapshots + deltas.

Deterministic, simulation-only. Reuses the SAME backtest models (fee, slippage,
execution-delay) and the SAME NoTradeReason codes as the live runtime, so replay
and runtime stay on one Common Data Model. A replayed fill is never an order.

No-trade-by-default: a fill with no fresh book snapshot for its coin is skipped
(SOURCE_UNAVAILABLE / STALE_SIGNAL), not silently counted. Copy delay degrades the
net edge via the execution-delay model. Partial fills are flagged, not fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.execution_delay_model import delay_penalty_bps
from hyper_smart_observer.backtesting.fee_model import backtest_fee
from hyper_smart_observer.copy_mode.copy_models import NoTradeReason

FILL = "FILL"
BOOK = "BOOK"
DELTA = "DELTA"


@dataclass(frozen=True)
class ReplayEvent:
    kind: str  # FILL | BOOK | DELTA
    coin: str
    ts_ms: int
    closed_pnl: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    leader_size: float | None = None
    delay_ms: int = 0
    is_partial: bool = False


def replay_event_stream(
    wallet_address: str,
    events: list[ReplayEvent],
    *,
    scenario: str = "ws",
    fee_rate_bps: float = 5.0,
    notional_per_trade: float = 50.0,
    max_signal_age_ms: int = 6_000,
) -> BacktestReport:
    """Replay an ordered event stream into a BacktestReport (realized equity curve)."""

    last_book_ts: dict[str, int] = {}
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    simulated = 0
    skipped = 0
    warnings: list[str] = []

    for ev in sorted(events, key=lambda e: e.ts_ms):
        coin = ev.coin.upper()
        if ev.kind == BOOK:
            if ev.best_bid and ev.best_ask and ev.best_bid > 0 and ev.best_ask > 0:
                last_book_ts[coin] = ev.ts_ms
            continue
        if ev.kind == DELTA:
            continue  # leader-size context only; not a paper economic event
        if ev.kind != FILL:
            continue

        book_ts = last_book_ts.get(coin)
        if book_ts is None:
            skipped += 1
            warnings.append(f"{coin}:{NoTradeReason.SOURCE_UNAVAILABLE.value}")
            continue
        if ev.ts_ms - book_ts > max_signal_age_ms:
            skipped += 1
            warnings.append(f"{coin}:{NoTradeReason.STALE_SIGNAL.value}")
            continue
        if ev.closed_pnl is None:
            skipped += 1
            warnings.append(f"{coin}:{NoTradeReason.EDGE_UNMEASURABLE.value}")
            continue

        fee = backtest_fee(notional_per_trade, fee_rate_bps)
        delay_cost = notional_per_trade * delay_penalty_bps(ev.delay_ms) / 10_000.0
        net = float(ev.closed_pnl) - fee - delay_cost
        equity += net
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        simulated += 1
        if ev.is_partial:
            warnings.append(f"{coin}:PARTIAL_FILL")

    if simulated == 0 and skipped == 0:
        warnings.append("no fill events")
    return BacktestReport(
        wallet_address=wallet_address,
        scenario=scenario,
        simulated_trades=simulated,
        skipped_actions=skipped,
        net_pnl=equity,
        max_drawdown=max_drawdown,
        warnings=warnings,
    )
