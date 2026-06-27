"""Additive runtime wiring for the copy dry-run (read-only, simulation-only).

Leaves copy_loop.run_copy_dry_run untouched. After a run it:
  * builds + persists a DecisionLedger (evidence chain) from the report's
    signal candidates and no-trade decisions;
  * derives a uniform SourceHealth list from the report's source_failures;
  * exposes a leader-exit adapter that follows CLOSE/REDUCE on OPEN paper trades
    via the existing PaperTradingSimulator (no parallel engine, never an order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hyper_smart_observer.ledger.decision_ledger import (
    DecisionLedgerEntry,
    DecisionLedgerExportResult,
    build_decision_ledger,
    write_decision_ledger,
)
from hyper_smart_observer.paper_trading.exit_engine import (
    ExitAction,
    LeaderExitSignal,
    OpenPaperPosition,
    decide_leader_exit,
)
from hyper_smart_observer.pipeline.source_health import SourceHealth, build_source_health


@dataclass(frozen=True)
class CopyRunEvidence:
    run_id: str
    ledger_entry_count: int
    ledger_json_path: str | None
    source_health: list[SourceHealth] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeLeaderExitEvidence:
    """Persisted evidence for local paper exits driven by leader reduce/close."""

    run_id: str
    close_results: list
    ledger_entries: list[DecisionLedgerEntry]
    ledger_json_path: str | None = None
    ledger_csv_path: str | None = None


def source_health_from_failures(source_failures: list[str] | None) -> list[SourceHealth]:
    out: list[SourceHealth] = []
    for failure in source_failures or []:
        text = str(failure)
        name = text.split(":", 1)[0] or "source"
        out.append(build_source_health(name, ok=False, degraded_reason=text))
    return out


def attach_evidence(report, *, reports_dir, features_by_coin: dict[str, Any] | None = None, run_id: str | None = None) -> CopyRunEvidence:
    rid = run_id or f"copy-run:{report.started_at.isoformat()}"
    entries = build_decision_ledger(
        report.signal_candidates, report.no_trade_decisions, features_by_coin, run_id=rid
    )
    json_path: str | None = None
    if entries:
        result = write_decision_ledger(entries, Path(reports_dir) / "decision_ledger", run_id=rid)
        json_path = str(result.json_path)
    return CopyRunEvidence(rid, len(entries), json_path, source_health_from_failures(report.source_failures))


def _open_positions_from_simulator(simulator) -> list[OpenPaperPosition]:
    positions: list[OpenPaperPosition] = []
    for row in simulator.list_open_trades():
        try:
            opened_at = datetime.fromisoformat(row["opened_at"])
        except (TypeError, ValueError, KeyError):
            continue
        positions.append(
            OpenPaperPosition(
                trade_id=row["trade_id"], coin=row["coin"], side=row["side"],
                entry_price=float(row["entry_price"]), size=float(row["size"]),
                opened_at=opened_at, wallet_address=row["wallet_address"],
            )
        )
    return positions


def apply_runtime_leader_exits(simulator, leader_exits: list[LeaderExitSignal]) -> list:
    """Follow leader CLOSE/REDUCE on the simulator's OPEN paper trades.

    Reuses exit_engine + PaperTradingSimulator close/partial-close methods. Re-reads open
    trades before each signal so sequential exits stay consistent. No order, ever.
    """
    results = []
    for signal in leader_exits:
        decisions = decide_leader_exit(signal, _open_positions_from_simulator(simulator))
        for decision in decisions:
            if decision.action == ExitAction.NO_TRADE or decision.trade_id is None:
                continue
            if decision.exit_reference_price is None or decision.exit_reference_price <= 0:
                continue
            reason = decision.trigger.value if decision.trigger else "EXIT"
            if decision.action == ExitAction.REDUCE:
                results.append(
                    simulator.partial_close_paper_trade(
                        decision.trade_id,
                        decision.exit_reference_price,
                        reason,
                        fraction=decision.reduce_fraction or 0.5,
                    )
                )
            else:
                results.append(simulator.close_paper_trade(decision.trade_id, decision.exit_reference_price, reason))
    return results


def apply_runtime_leader_exits_with_evidence(
    simulator,
    leader_exits: list[LeaderExitSignal],
    *,
    reports_dir,
    run_id: str,
    features_by_coin: dict[str, Any] | None = None,
    write_ledger: bool = True,
) -> RuntimeLeaderExitEvidence:
    """Follow leader exits and persist a DecisionLedger proof for each outcome.

    This is still local paper simulation only. It reuses the existing
    ``PaperTradingSimulator.close_paper_trade`` and records both successful
    closes/reduces and NO_TRADE exit refusals. No network write, no order.
    """

    close_results = []
    entries: list[DecisionLedgerEntry] = []
    sequence = 0
    for signal in leader_exits:
        decisions = decide_leader_exit(signal, _open_positions_from_simulator(simulator))
        feature = _feature_for(features_by_coin, signal.coin)
        for decision in decisions:
            sequence += 1
            close_result = None
            reason_codes = tuple(decision.reason_codes)
            decision_type = "PAPER_EXIT_NO_TRADE"
            trade_id = decision.trade_id
            realized_net_pnl = None
            if (
                decision.action != ExitAction.NO_TRADE
                and decision.trade_id is not None
                and decision.exit_reference_price is not None
                and decision.exit_reference_price > 0
            ):
                reason = decision.trigger.value if decision.trigger else "EXIT"
                if decision.action == ExitAction.REDUCE:
                    close_result = simulator.partial_close_paper_trade(
                        decision.trade_id,
                        decision.exit_reference_price,
                        reason,
                        fraction=decision.reduce_fraction or 0.5,
                    )
                else:
                    close_result = simulator.close_paper_trade(decision.trade_id, decision.exit_reference_price, reason)
                close_results.append(close_result)
                realized_net_pnl = close_result.net_pnl
                reason_codes = (reason,) if close_result.success else (close_result.message,)
                decision_type = "PAPER_EXIT_REDUCE" if decision.action == ExitAction.REDUCE else "PAPER_EXIT_CLOSE"
                trade_id = close_result.realized_trade_id or close_result.trade_id
            entries.append(
                DecisionLedgerEntry(
                    run_id=run_id,
                    decision_id=f"exit:{run_id}:{sequence}",
                    decision_type=decision_type,
                    paper_intent_id=None,
                    paper_trade_id=trade_id,
                    coin=signal.coin.upper(),
                    wallet=signal.wallet_address or "",
                    reason_codes=reason_codes,
                    feature_hash=getattr(feature, "feature_hash", None),
                    edge_remaining_bps=None,
                    spread_bps=getattr(feature, "spread_bps", None),
                    liquidity_score=getattr(feature, "liquidity_score", None),
                    copy_degradation_bps=None,
                    source_health=str(getattr(feature, "source_health", "PAPER_EXIT")),
                    raw_refs=_exit_raw_refs(feature),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    exit_trigger=decision.trigger.value if decision.trigger else None,
                    exit_reference_price=decision.exit_reference_price,
                    realized_net_pnl=realized_net_pnl,
                ).with_hash()
            )
    json_path = None
    csv_path = None
    if entries and write_ledger:
        export: DecisionLedgerExportResult = write_decision_ledger(
            entries,
            Path(reports_dir) / "decision_ledger",
            run_id=f"{run_id}:leader-exits",
        )
        json_path = str(export.json_path)
        csv_path = str(export.csv_path)
    return RuntimeLeaderExitEvidence(run_id, close_results, entries, json_path, csv_path)


def _feature_for(features_by_coin: dict[str, Any] | None, coin: str | None) -> Any:
    if not features_by_coin or not coin:
        return None
    return features_by_coin.get(coin.upper())


def _exit_raw_refs(feature: Any) -> tuple[str, ...]:
    refs = ["leaderDelta", "paperTrade", "PaperTradingSimulator"]
    if feature is not None:
        refs.extend(["allMids", "l2Book"])
        if getattr(feature, "volatility_context", None) is not None:
            refs.append("candleSnapshot")
    return tuple(refs)
