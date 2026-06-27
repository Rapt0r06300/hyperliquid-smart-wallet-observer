from __future__ import annotations

from hl_observer.copying.leaderboard_autoselect import CopyLeaderAutoSelectReport
from hl_observer.copying.signal_detector import CopySignalDetectionReport
from hl_observer.storage.models import FollowDecision, PaperFollowOrder, TopWallet


def format_copy_run_report(
    *,
    leaders: CopyLeaderAutoSelectReport | None,
    signals: CopySignalDetectionReport,
) -> str:
    lines = [
        "copy-run dry-run report",
        "mode: PAPER mock USDC only",
        "real Hyperliquid orders: 0",
        "virtual simulation positions: opened/closed only when paper gates pass",
        "testnet execution: locked",
        f"poll interval seconds: {signals.interval_seconds}",
    ]
    if leaders is not None:
        lines.extend(
            [
                f"leaderboard candidates seen: {leaders.candidates_seen}",
                f"leaders auto-selected: {leaders.accepted_count}/{leaders.target_leaders}",
            ]
        )
    lines.extend(
        [
            f"deltas seen: {signals.deltas_seen}",
            f"signals created: {signals.signals_created}",
            f"virtual entries accepted locally: {signals.paper_candidates}",
            f"rejected: {signals.rejected}",
        ]
    )
    if signals.no_trade_reasons:
        lines.append("no-trade reasons:")
        for reason, count in sorted(signals.no_trade_reasons.items()):
            lines.append(f"- {reason}: {count}")
    for signal in signals.signals[:10]:
        lines.append(
            f"- {signal.id} {signal.source_wallet} {signal.coin} {signal.signal_type}/{signal.side} "
            f"edge={signal.edge_remaining_bps:.1f} decision={signal.decision.value}"
        )
    return "\n".join(lines)


def format_copy_status_report(
    *,
    period: str,
    top_wallets: list[TopWallet],
    decisions: list[FollowDecision],
    paper_orders: list[PaperFollowOrder],
) -> str:
    allowed = sum(1 for decision in decisions if decision.allowed)
    rejected = len(decisions) - allowed
    paper_notional = sum(float(order.notional_usdc or 0.0) for order in paper_orders)
    lines = [
        "copy-report",
        f"period: {period}",
        "mode: research/paper only",
        f"top wallets followed: {len(top_wallets)}",
        f"follow decisions: {len(decisions)}",
        f"paper allowed decisions: {allowed}",
        f"rejected/observe-only decisions: {rejected}",
        f"paper mock USDC notional simulated: {paper_notional:.2f}",
        "no live orders, no mainnet, no testnet execution by default",
    ]
    return "\n".join(lines)
