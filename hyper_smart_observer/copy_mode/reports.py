from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_models import CopyRunReport, to_jsonable
from hyper_smart_observer.copy_mode.repository import list_latest_signal_candidates, list_no_trade_decisions
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import paper_trades_repo


@dataclass(frozen=True)
class CopyPeriodPnlReport:
    generated_at: str
    period: str
    scope: str
    starting_equity: float
    current_equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_fees: float
    max_drawdown: float
    open_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    signal_candidates: int
    no_trade_decisions: int
    disclaimer: str


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
        f"scan_features_rows: {report.scan_features_rows}",
        f"decision_ledger_entries: {report.decision_ledger_entries}",
    ]
    if report.scan_features_json_path:
        lines.append(f"scan_features_json: {report.scan_features_json_path}")
    if report.scan_features_csv_path:
        lines.append(f"scan_features_csv: {report.scan_features_csv_path}")
    if report.decision_ledger_json_path:
        lines.append(f"decision_ledger_json: {report.decision_ledger_json_path}")
    if report.decision_ledger_csv_path:
        lines.append(f"decision_ledger_csv: {report.decision_ledger_csv_path}")
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


def build_copy_period_pnl_report(config: AppConfig, period: str) -> CopyPeriodPnlReport:
    initialize_database(config)
    with get_connection(config) as conn:
        signal_count = len(list_latest_signal_candidates(conn, limit=10_000))
        no_trade_count = len(list_no_trade_decisions(conn, limit=10_000))
        open_rows = paper_trades_repo.list_open_paper_trades(conn)
        closed_rows = paper_trades_repo.list_closed_paper_trades(conn, limit=10_000)
    starting_equity = float(config.paper_starting_equity)
    realized_pnl = sum(float(row["net_pnl"] or row["pnl"] or 0.0) for row in closed_rows)
    total_fees = sum(
        float(row["fee_entry"] or row["simulated_fee"] or 0.0) + float(row["fee_exit"] or 0.0)
        for row in [*open_rows, *closed_rows]
    )
    max_drawdown = _realized_max_drawdown(closed_rows, starting_equity)
    wins = sum(1 for row in closed_rows if float(row["net_pnl"] or row["pnl"] or 0.0) > 0)
    losses = sum(1 for row in closed_rows if float(row["net_pnl"] or row["pnl"] or 0.0) < 0)
    closed = len(closed_rows)
    win_rate = (wins / closed * 100.0) if closed else 0.0
    return CopyPeriodPnlReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        period=period,
        scope="research_only_local_paper",
        starting_equity=starting_equity,
        current_equity=starting_equity + realized_pnl,
        realized_pnl=realized_pnl,
        unrealized_pnl=0.0,
        total_fees=total_fees,
        max_drawdown=max_drawdown,
        open_trades=len(open_rows),
        closed_trades=closed,
        winning_trades=wins,
        losing_trades=losses,
        win_rate_pct=win_rate,
        signal_candidates=signal_count,
        no_trade_decisions=no_trade_count,
        disclaimer="Local paper report only. Historical/paper result is not future profit. No real order.",
    )


def write_copy_period_pnl_report(report: CopyPeriodPnlReport, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_period = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in report.period) or "period"
    stamp = report.generated_at.replace(":", "").replace("-", "").replace(".", "_")
    base = f"copy_period_report_{safe_period}_{stamp}"
    json_path = output_dir / f"{base}.json"
    csv_path = output_dir / f"{base}.csv"
    md_path = output_dir / f"{base}.md"
    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(payload.keys()))
        writer.writeheader()
        writer.writerow(payload)
    md_path.write_text(format_copy_period_report_from_object(report), encoding="utf-8")
    return json_path, csv_path, md_path


def format_copy_period_report_from_object(report: CopyPeriodPnlReport) -> str:
    return "\n".join(
        [
            "HyperSmart copy-report",
            f"period: {report.period}",
            f"scope: {report.scope}",
            f"signal candidates: {report.signal_candidates}",
            f"no-trade decisions: {report.no_trade_decisions}",
            f"open paper simulations: {report.open_trades}",
            f"closed paper simulations: {report.closed_trades}",
            f"paper realized PnL: {report.realized_pnl:.2f}",
            f"paper current equity: {report.current_equity:.2f}",
            f"paper max drawdown: {report.max_drawdown:.2f}",
            f"paper total fees: {report.total_fees:.2f}",
            f"paper win rate: {report.win_rate_pct:.2f}%",
            report.disclaimer,
        ]
    )


def format_copy_period_report(
    period: str,
    *,
    no_trade_count: int,
    signal_count: int,
    paper_pnl: float = 0.0,
    max_drawdown: float = 0.0,
    total_fees: float = 0.0,
    open_trades: int = 0,
    closed_trades: int = 0,
    win_rate_pct: float = 0.0,
) -> str:
    return "\n".join(
        [
            "HyperSmart copy-report",
            f"period: {period}",
            "scope: research/paper only",
            f"signal candidates: {signal_count}",
            f"no-trade decisions: {no_trade_count}",
            f"paper mock USDC net PnL: {paper_pnl:.2f}",
            f"paper max drawdown: {max_drawdown:.2f}",
            f"paper total fees: {total_fees:.2f}",
            f"open paper simulations: {open_trades}",
            f"closed paper simulations: {closed_trades}",
            f"paper win rate: {win_rate_pct:.2f}%",
            "No real order. Historical/paper result is not future profit.",
        ]
    )


def _realized_max_drawdown(closed_rows, starting_equity: float) -> float:
    equity = float(starting_equity)
    peak = equity
    max_dd = 0.0
    for row in sorted(closed_rows, key=lambda r: (r["closed_at"] or "")):
        equity += float(row["net_pnl"] or row["pnl"] or 0.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd
