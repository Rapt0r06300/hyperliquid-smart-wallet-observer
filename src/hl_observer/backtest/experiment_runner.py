"""Experiment runner (V12 capability R, repo 11): run a backtest experiment honestly.

Validates inputs via the runner contract, then walks events in time order, passing each
decide_fn ONLY the past events (no lookahead), and produces a report. Pure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from hl_observer.backtest.runner_contract import assert_runner_inputs


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    name: str
    run_context: str
    total_events: int
    decisions: tuple[dict, ...] = field(default_factory=tuple)
    accepted: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "run_context": self.run_context,
            "total_events": self.total_events,
            "accepted": self.accepted,
            "decisions": list(self.decisions),
        }


def run_experiment(
    name: str,
    run_context,
    events: list[dict],
    decide_fn: Callable[[dict, list[dict]], dict],
    *,
    min_gap_ms: int = 0,
) -> ExperimentResult:
    assert_runner_inputs(run_context, events, min_gap_ms=min_gap_ms)
    ordered = sorted(events, key=lambda e: int(e.get("decision_ts_ms", e.get("data_ts_ms", 0))))
    decisions: list[dict] = []
    accepted = 0
    for i, ev in enumerate(ordered):
        past = ordered[:i]                       # only the past is visible
        d = decide_fn(ev, past) or {}
        decisions.append(d)
        if d.get("accepted"):
            accepted += 1
    rc = run_context.value if hasattr(run_context, "value") else str(run_context)
    return ExperimentResult(name=name, run_context=rc, total_events=len(ordered),
                            decisions=tuple(decisions), accepted=accepted)


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    """Resume PnL honnete d'un ensemble de decisions/trades paper.

    profit_factor = gross_profit / gross_loss (juge de paix, pas le winrate brut).
    Pur ; ne presume aucun fill parfait ; travaille sur les PnL realises fournis.
    """

    total_trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    total_pnl: float
    expectancy: float
    max_drawdown: float

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 6),
            "gross_profit": round(self.gross_profit, 8),
            "gross_loss": round(self.gross_loss, 8),
            "profit_factor": (float("inf") if self.profit_factor == float("inf")
                              else round(self.profit_factor, 6)),
            "total_pnl": round(self.total_pnl, 8),
            "expectancy": round(self.expectancy, 8),
            "max_drawdown": round(self.max_drawdown, 8),
        }


def summarize_pnl(realized_pnls) -> BacktestSummary:
    """Profit factor, winrate, expectancy et max drawdown depuis une liste de
    PnL realises (un par trade clos). Aucune donnee inventee."""
    pnls = [float(x) for x in realized_pnls if x is not None]
    wins = [p for p in pnls if p > 0.0]
    losses = [p for p in pnls if p < 0.0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)  # positif
    total = sum(pnls)
    n = len(pnls)
    if gross_loss > 0.0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0.0:
        pf = float("inf")
    else:
        pf = 0.0
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return BacktestSummary(
        total_trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=(len(wins) / n if n else 0.0),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=pf,
        total_pnl=total,
        expectancy=(total / n if n else 0.0),
        max_drawdown=max_dd,
    )


def summarize_decisions(decisions, pnl_key: str = "realized_pnl") -> BacktestSummary:
    """Extrait les PnL realises des decisions acceptees et calcule le resume."""
    pnls = [
        d[pnl_key]
        for d in decisions
        if isinstance(d, dict) and d.get("accepted") and d.get(pnl_key) is not None
    ]
    return summarize_pnl(pnls)


__all__ = [
    "ExperimentResult",
    "run_experiment",
    "BacktestSummary",
    "summarize_pnl",
    "summarize_decisions",
]
