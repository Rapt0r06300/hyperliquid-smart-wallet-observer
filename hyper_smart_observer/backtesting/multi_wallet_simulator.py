from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Any


@dataclass(frozen=True)
class WalletFollowSimulationResult:
    wallet_address: str
    total_fills: int
    usable_closed_pnl_points: int
    skipped_actions: int
    gross_pnl: float
    total_costs: float
    net_pnl: float
    winrate: float | None
    max_drawdown: float
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MultiWalletFollowSimulationReport:
    generated_at: datetime
    scenario: str
    requested_wallets: int
    simulated_wallets: int
    notional_per_trade: float
    delay_seconds: float
    total_usable_trades: int
    total_skipped_actions: int
    gross_pnl: float
    total_costs: float
    net_pnl: float
    max_drawdown: float
    wallet_results: list[WalletFollowSimulationResult]
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = (
        "Local historical replay only. This is not a trading signal, not an order, "
        "and historical performance is not future profit."
    )


def simulate_multi_wallet_following(
    wallet_rows: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    notional_per_trade: float = 50.0,
    fee_bps: float = 5.0,
    spread_bps: float = 2.0,
    slippage_bps: float = 5.0,
    delay_seconds: float = 300.0,
    delay_bps_per_second: float = 0.01,
    scenario: str = "multi_wallet_follow_closed_pnl",
) -> MultiWalletFollowSimulationReport:
    if notional_per_trade <= 0:
        raise ValueError("notional_per_trade must be positive")
    if min(fee_bps, spread_bps, slippage_bps, delay_seconds, delay_bps_per_second) < 0:
        raise ValueError("cost and delay parameters must be non-negative")

    results: list[WalletFollowSimulationResult] = []
    combined_equity: list[float] = []
    warnings: list[str] = []
    for wallet, rows_iter in wallet_rows.items():
        rows = list(rows_iter)
        result, wallet_net_values = simulate_wallet_following_from_fills(
            wallet,
            rows,
            notional_per_trade=notional_per_trade,
            fee_bps=fee_bps,
            spread_bps=spread_bps,
            slippage_bps=slippage_bps,
            delay_seconds=delay_seconds,
            delay_bps_per_second=delay_bps_per_second,
        )
        results.append(result)
        combined_equity.extend(wallet_net_values)
        if result.usable_closed_pnl_points == 0:
            warnings.append(f"{wallet}: no usable closedPnl points")
    total_gross = sum(result.gross_pnl for result in results)
    total_costs = sum(result.total_costs for result in results)
    total_net = sum(result.net_pnl for result in results)
    return MultiWalletFollowSimulationReport(
        generated_at=datetime.now(UTC),
        scenario=scenario,
        requested_wallets=len(wallet_rows),
        simulated_wallets=sum(1 for result in results if result.usable_closed_pnl_points > 0),
        notional_per_trade=notional_per_trade,
        delay_seconds=delay_seconds,
        total_usable_trades=sum(result.usable_closed_pnl_points for result in results),
        total_skipped_actions=sum(result.skipped_actions for result in results),
        gross_pnl=round(total_gross, 8),
        total_costs=round(total_costs, 8),
        net_pnl=round(total_net, 8),
        max_drawdown=round(_max_drawdown(combined_equity), 8),
        wallet_results=results,
        warnings=warnings,
    )


def simulate_wallet_following_from_fills(
    wallet_address: str,
    rows: list[Mapping[str, Any]],
    *,
    notional_per_trade: float,
    fee_bps: float,
    spread_bps: float,
    slippage_bps: float,
    delay_seconds: float,
    delay_bps_per_second: float,
) -> tuple[WalletFollowSimulationResult, list[float]]:
    net_values: list[float] = []
    gross_values: list[float] = []
    skipped = 0
    warnings: list[str] = []
    per_trade_cost = notional_per_trade * (
        (fee_bps * 2.0 + spread_bps * 2.0 + slippage_bps * 2.0 + delay_seconds * delay_bps_per_second)
        / 10_000.0
    )
    for row in rows:
        closed_pnl = _float_or_none(row.get("closed_pnl"))
        price = _float_or_none(row.get("price"))
        size = _float_or_none(row.get("size"))
        if closed_pnl is None or price is None or size is None or price <= 0 or size == 0:
            skipped += 1
            continue
        leader_notional = abs(price * size)
        if leader_notional <= 0:
            skipped += 1
            continue
        # Use bps-based replay to maintain leader edge proportions
        pnl_bps = closed_pnl / leader_notional * 10_000.0
        gross = notional_per_trade * pnl_bps / 10_000.0

        # Standardized accounting: subtract all replayed trip costs
        net = gross - per_trade_cost
        gross_values.append(gross)
        net_values.append(net)
    if not net_values:
        warnings.append("insufficient closedPnl/price/size data for replay")
    wins = sum(1 for value in net_values if value > 0)
    winrate = wins / len(net_values) if net_values else None
    result = WalletFollowSimulationResult(
        wallet_address=wallet_address.lower(),
        total_fills=len(rows),
        usable_closed_pnl_points=len(net_values),
        skipped_actions=skipped,
        gross_pnl=round(sum(gross_values), 8),
        total_costs=round(per_trade_cost * len(net_values), 8),
        net_pnl=round(sum(net_values), 8),
        winrate=winrate,
        max_drawdown=round(_max_drawdown(net_values), 8),
        warnings=warnings,
    )
    return result, net_values


def write_multi_wallet_simulation_report(
    report: MultiWalletFollowSimulationReport,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"multi_wallet_follow_simulation_{stamp}.json"
    md_path = output_dir / f"multi_wallet_follow_simulation_{stamp}.md"
    json_path.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(format_multi_wallet_simulation_markdown(report), encoding="utf-8")
    return json_path, md_path


def format_multi_wallet_simulation_markdown(report: MultiWalletFollowSimulationReport) -> str:
    lines = [
        "# HyperSmart Multi-Wallet Follow Simulation",
        "",
        report.disclaimer,
        "",
        f"- scenario: `{report.scenario}`",
        f"- requested_wallets: {report.requested_wallets}",
        f"- simulated_wallets: {report.simulated_wallets}",
        f"- notional_per_trade: {report.notional_per_trade:.2f}",
        f"- delay_seconds: {report.delay_seconds:.2f}",
        f"- total_usable_trades: {report.total_usable_trades}",
        f"- total_skipped_actions: {report.total_skipped_actions}",
        f"- gross_pnl: {report.gross_pnl:.4f}",
        f"- total_costs: {report.total_costs:.4f}",
        f"- net_pnl: {report.net_pnl:.4f}",
        f"- max_drawdown: {report.max_drawdown:.4f}",
        "",
        "## Wallets",
        "",
        "| Wallet | Usable | Skipped | Gross | Costs | Net | Winrate | Max DD | Warnings |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in report.wallet_results:
        winrate = "" if result.winrate is None else f"{result.winrate:.2%}"
        warnings = ", ".join(result.warnings)
        lines.append(
            f"| `{result.wallet_address}` | {result.usable_closed_pnl_points} | {result.skipped_actions} | "
            f"{result.gross_pnl:.4f} | {result.total_costs:.4f} | {result.net_pnl:.4f} | "
            f"{winrate} | {result.max_drawdown:.4f} | {warnings} |"
        )
    if report.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines) + "\n"


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _jsonable(report: MultiWalletFollowSimulationReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["generated_at"] = report.generated_at.isoformat()
    return payload
