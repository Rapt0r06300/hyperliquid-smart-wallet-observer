from __future__ import annotations

import json
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_models import CopyRunReport, to_jsonable


def format_copy_run_report(report: CopyRunReport) -> str:
    lines = [
        "HyperSmart copy-run dry-run",
        "mode: PAPER_MOCK_USDC only",
        "orders: 0",
        "mainnet: forbidden",
        f"interval_seconds: {report.interval_seconds}",
        f"network_read: {report.network_read}",
        f"ws: {report.ws}",
        f"leaders_seen: {report.leaders_seen}",
        f"deltas_seen: {report.deltas_seen}",
        f"signal_candidates: {len(report.signal_candidates)}",
        f"no_trade_decisions: {len(report.no_trade_decisions)}",
    ]
    if report.source_failures:
        lines.append("source_failures:")
        lines.extend(f"- {failure}" for failure in report.source_failures)
    if report.no_trade_decisions:
        lines.append("no_trade:")
        for decision in report.no_trade_decisions[:20]:
            lines.append(f"- {decision.reason.value}: {decision.observed} -> {decision.next_action}")
    return "\n".join(lines)


def write_copy_run_report(report: CopyRunReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "copy_run_report.json"
    path.write_text(json.dumps(to_jsonable(report), indent=2, sort_keys=True), encoding="utf-8")
    return path


def format_copy_period_report(period: str, *, no_trade_count: int, signal_count: int, paper_pnl: float = 0.0) -> str:
    return "\n".join(
        [
            "HyperSmart copy-report",
            f"period: {period}",
            "scope: research/paper only",
            f"signal candidates: {signal_count}",
            f"no-trade decisions: {no_trade_count}",
            f"paper mock USDC net PnL: {paper_pnl:.2f}",
            "No real order. Historical/paper result is not future profit.",
        ]
    )
