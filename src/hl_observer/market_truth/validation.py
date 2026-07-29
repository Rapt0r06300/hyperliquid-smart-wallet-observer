"""Research verdict after causal OOS, walk-forward and forward-paper checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from hl_observer.backtesting.validation_gates import (
    max_drawdown,
    profit_factor,
    run_validation_gates,
)


@dataclass(frozen=True, slots=True)
class ResearchVerdict:
    verdict: str
    reason: str
    backtest: Mapping[str, Any]
    forward: Mapping[str, Any]
    quality_violations: int
    reconciliation_violations: int
    paper_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "backtest": dict(self.backtest),
            "forward": dict(self.forward),
            "quality_violations": self.quality_violations,
            "reconciliation_violations": self.reconciliation_violations,
            "paper_only": True,
            "real_execution": False,
            "profit_guaranteed": False,
        }


def evaluate_research_candidate(
    *,
    backtest_trades: Iterable[Any],
    forward_trades: Iterable[Any],
    evidence: Iterable[Mapping[str, Any]] = (),
    causal_events: Iterable[Mapping[str, Any]] = (),
    min_backtest_trades: int = 30,
    min_backtest_pf: float = 1.10,
    min_oos_pf: float = 1.0,
    min_forward_trades: int = 10,
    min_forward_pf: float = 1.05,
    max_forward_drawdown_usdc: float = 25.0,
) -> ResearchVerdict:
    """Return PEPITE only after both causal backtest and real forward paper pass."""
    evidence_rows = list(evidence)
    quality_violations = sum(
        1
        for row in evidence_rows
        if not bool((row.get("fill") or {}).get("feed_quality_score"))
        or str((row.get("fill") or {}).get("status") or "")
        in {"QUALITY_BLOCKED", "STALE_BOOK", "UNMEASURABLE"}
    )
    reconciliation_violations = sum(
        1
        for row in evidence_rows
        if not bool((row.get("reconciliation") or {}).get("ok", False))
    )
    backtest_rows = list(backtest_trades)
    forward_rows = list(forward_trades)
    backtest_report = run_validation_gates(
        backtest_rows,
        events=list(causal_events),
        min_trades=min_backtest_trades,
        min_pf=min_backtest_pf,
        min_oos_pf=min_oos_pf,
    )
    forward_pnls = _pnls(forward_rows)
    forward_pf = profit_factor(forward_pnls)
    forward_net = sum(forward_pnls)
    forward_dd = max_drawdown(forward_pnls)
    forward_report = {
        "trades": len(forward_pnls),
        "profit_factor": "inf" if forward_pf == float("inf") else round(forward_pf, 6),
        "net_pnl_usdc": round(forward_net, 10),
        "max_drawdown_usdc": round(forward_dd, 10),
        "min_trades": int(min_forward_trades),
        "min_profit_factor": float(min_forward_pf),
        "max_drawdown_limit_usdc": float(max_forward_drawdown_usdc),
    }
    if quality_violations or reconciliation_violations:
        return ResearchVerdict(
            verdict="KILL",
            reason="TRUTH_OR_DATA_QUALITY_VIOLATION",
            backtest=backtest_report,
            forward=forward_report,
            quality_violations=quality_violations,
            reconciliation_violations=reconciliation_violations,
        )
    if backtest_report.get("verdict") != "DEPLOY_CANDIDATE":
        return ResearchVerdict(
            verdict="KILL",
            reason="OOS_OR_WALK_FORWARD_FAILED",
            backtest=backtest_report,
            forward=forward_report,
            quality_violations=0,
            reconciliation_violations=0,
        )
    if len(forward_pnls) < int(min_forward_trades):
        return ResearchVerdict(
            verdict="FORWARD_PAPER",
            reason="FORWARD_SAMPLE_INSUFFICIENT",
            backtest=backtest_report,
            forward=forward_report,
            quality_violations=0,
            reconciliation_violations=0,
        )
    if (
        forward_pf < float(min_forward_pf)
        or forward_net <= 0
        or forward_dd > float(max_forward_drawdown_usdc)
    ):
        return ResearchVerdict(
            verdict="KILL",
            reason="FORWARD_PAPER_FAILED",
            backtest=backtest_report,
            forward=forward_report,
            quality_violations=0,
            reconciliation_violations=0,
        )
    return ResearchVerdict(
        verdict="PEPITE",
        reason="OOS_AND_FORWARD_PAPER_PASSED",
        backtest=backtest_report,
        forward=forward_report,
        quality_violations=0,
        reconciliation_violations=0,
    )


def _pnls(trades: Iterable[Any]) -> list[float]:
    values: list[float] = []
    for trade in trades:
        value = (
            trade
            if isinstance(trade, (int, float))
            else trade.get("net_pnl_usdc", trade.get("pnl"))
            if isinstance(trade, Mapping)
            else getattr(trade, "net_pnl_usdc", getattr(trade, "pnl", None))
        )
        try:
            if value is not None:
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


__all__ = ["ResearchVerdict", "evaluate_research_candidate"]
