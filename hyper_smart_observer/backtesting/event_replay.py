"""Replay événementiel déterministe sur fills, carnets et deltas Hyperliquid.

Simulation locale uniquement. Le moteur refuse par défaut les fills sans carnet
frais, facture explicitement frais/spread/slippage/latence, traite les missed
fills et réduit économiquement les partial fills au lieu de fabriquer une
exécution complète.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    fill_fraction: float = 1.0
    missed_fill: bool = False


def replay_event_stream(
    wallet_address: str,
    events: list[ReplayEvent],
    *,
    scenario: str = "ws",
    fee_rate_bps: float = 5.0,
    notional_per_trade: float = 50.0,
    slippage_bps: float = 5.0,
    delay_bps_per_second: float = 1.0,
    fee_sides: int = 2,
    max_signal_age_ms: int = 6_000,
) -> BacktestReport:
    """Rejoue une suite ordonnée et retourne une preuve économique nette.

    ``closed_pnl`` reste la mesure historique observée côté leader. Le moteur ne
    l'améliore jamais : il la réduit par le taux de fill puis retranche tous les
    coûts de copie. Le spread provient du dernier BBO/carnet frais disponible.
    """

    if notional_per_trade <= 0:
        raise ValueError("notional_per_trade must be positive")
    if min(fee_rate_bps, slippage_bps, delay_bps_per_second, max_signal_age_ms) < 0:
        raise ValueError("replay costs and freshness must be non-negative")
    if fee_sides < 1:
        raise ValueError("fee_sides must be >= 1")

    last_book: dict[str, tuple[int, float, float]] = {}
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    simulated = 0
    skipped = 0
    warnings: list[str] = []
    equity_curve: list[float] = []
    gross_total = 0.0
    fee_total = 0.0
    spread_total = 0.0
    slippage_total = 0.0
    delay_total = 0.0

    for ev in sorted(events, key=lambda e: e.ts_ms):
        coin = ev.coin.upper()
        if ev.kind == BOOK:
            bid = _positive(ev.best_bid)
            ask = _positive(ev.best_ask)
            if bid is None or ask is None or bid > ask:
                warnings.append(f"{coin}:INVALID_BOOK")
                continue
            last_book[coin] = (ev.ts_ms, bid, ask)
            continue
        if ev.kind == DELTA:
            continue  # contexte leader seulement, jamais une exécution implicite
        if ev.kind != FILL:
            skipped += 1
            warnings.append(f"{coin}:UNKNOWN_EVENT_KIND")
            continue
        if ev.missed_fill:
            skipped += 1
            warnings.append(f"{coin}:MISSED_FILL")
            continue
        if not 0.0 < ev.fill_fraction <= 1.0:
            skipped += 1
            warnings.append(f"{coin}:INVALID_FILL_FRACTION")
            continue

        book = last_book.get(coin)
        if book is None:
            skipped += 1
            warnings.append(f"{coin}:{NoTradeReason.SOURCE_UNAVAILABLE.value}")
            continue
        book_ts, bid, ask = book
        if ev.ts_ms - book_ts > max_signal_age_ms:
            skipped += 1
            warnings.append(f"{coin}:{NoTradeReason.STALE_SIGNAL.value}")
            continue
        if ev.closed_pnl is None:
            skipped += 1
            warnings.append(f"{coin}:{NoTradeReason.EDGE_UNMEASURABLE.value}")
            continue
        if ev.delay_ms < 0:
            skipped += 1
            warnings.append(f"{coin}:INVALID_DELAY")
            continue

        fill_fraction = float(ev.fill_fraction)
        copied_notional = notional_per_trade * fill_fraction
        gross = float(ev.closed_pnl) * fill_fraction
        mid = (bid + ask) / 2.0
        observed_spread_bps = ((ask - bid) / mid) * 10_000.0 if mid > 0 else 0.0
        fee_cost = backtest_fee(copied_notional, fee_rate_bps) * float(fee_sides)
        spread_cost = copied_notional * observed_spread_bps / 10_000.0
        slippage_cost = copied_notional * (slippage_bps * 2.0) / 10_000.0
        delay_cost = copied_notional * delay_penalty_bps(
            ev.delay_ms,
            bps_per_second=delay_bps_per_second,
        ) / 10_000.0
        costs = fee_cost + spread_cost + slippage_cost + delay_cost
        net = gross - costs

        gross_total += gross
        fee_total += fee_cost
        spread_total += spread_cost
        slippage_total += slippage_cost
        delay_total += delay_cost
        equity += net
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        simulated += 1
        if ev.is_partial or fill_fraction < 1.0:
            warnings.append(f"{coin}:PARTIAL_FILL:{fill_fraction:.4f}")

    if simulated == 0 and skipped == 0:
        warnings.append("no fill events")
    total_costs = fee_total + spread_total + slippage_total + delay_total
    return BacktestReport(
        wallet_address=wallet_address,
        scenario=scenario,
        simulated_trades=simulated,
        skipped_actions=skipped,
        net_pnl=equity,
        max_drawdown=max_drawdown,
        warnings=warnings,
        gross_pnl=gross_total,
        total_costs=total_costs,
        equity_curve=equity_curve,
        cost_breakdown={
            "fees": fee_total,
            "spread": spread_total,
            "slippage": slippage_total,
            "delay": delay_total,
        },
    )


def _positive(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None
