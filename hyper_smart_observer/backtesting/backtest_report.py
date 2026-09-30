from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass(frozen=True)
class BacktestReport:
    wallet_address: str
    scenario: str
    simulated_trades: int
    skipped_actions: int
    net_pnl: float
    max_drawdown: float
    warnings: list[str] = field(default_factory=list)
    gross_pnl: float | None = None
    total_costs: float | None = None
    equity_curve: list[float] = field(default_factory=list)
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    disclaimer: str = "backtest local simulation only; historical simulation is not future profit"

    def __post_init__(self) -> None:
        if self.gross_pnl is not None and self.total_costs is not None:
            expected = float(self.gross_pnl) - float(self.total_costs)
            if abs(expected - float(self.net_pnl)) > 1e-6:
                raise ValueError("BacktestReport incohérent: gross_pnl - total_costs != net_pnl")
        if any(value < 0 for value in self.cost_breakdown.values()):
            raise ValueError("BacktestReport refuse les coûts négatifs artificiels.")


def write_backtest_report(report: BacktestReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_wallet = report.wallet_address.replace(":", "_").replace("/", "_").replace("\\", "_")
    path = output_dir / f"backtest_{safe_wallet}_{report.scenario}.json"
    path.write_text(json.dumps(report.__dict__, indent=2, sort_keys=True), encoding="utf-8")
    return path
