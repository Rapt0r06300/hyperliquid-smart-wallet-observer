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
    disclaimer: str = "backtest local simulation only; historical simulation is not future profit"


def write_backtest_report(report: BacktestReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_wallet = report.wallet_address.replace(":", "_").replace("/", "_").replace("\\", "_")
    path = output_dir / f"backtest_{safe_wallet}_{report.scenario}.json"
    path.write_text(json.dumps(report.__dict__, indent=2, sort_keys=True), encoding="utf-8")
    return path
