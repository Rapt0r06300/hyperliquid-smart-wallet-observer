from __future__ import annotations

from pathlib import Path
from time import time

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_models import CopyRunReport, CopySizingInput, DeltaAction, LeaderDelta, LeaderStatus, NoTradeReason, stable_hash, utc_now
from hyper_smart_observer.copy_mode.copy_signal_detector import detect_signal_candidates
from hyper_smart_observer.copy_mode.delta_detector import classify_fill_delta, diff_position_snapshots
from hyper_smart_observer.copy_mode.leaderboard_selector import LeaderboardShortlistReport, load_shortlist_entries, write_shortlist_report
from hyper_smart_observer.copy_mode.no_trade_report import decision_from_reason, write_no_trade_reports
from hyper_smart_observer.copy_mode.repository import insert_leader_delta, insert_no_trade_decision, insert_signal_candidate, insert_shortlist_entries
from hyper_smart_observer.copy_mode.sizing import calculate_paper_copy_sizing
from hyper_smart_observer.copy_mode.snapshot_engine import (
    InfoClientLike,
    collect_leader_snapshot,
    finish_collection_run,
    latest_previous_positions,
    start_collection_run,
)
from hyper_smart_observer.hyperliquid_client.info_client import HyperliquidInfoClient
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.reports.french_formatter import format_french_summary
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.research_ledger import ResearchHistoryLedger


def shortlist_path(config: AppConfig) -> Path:
    return Path(config.runtime_root) / "data" / "leaderboard_shortlist.json"


def run_copy_dry_run(
    config: AppConfig,
    *,
    interval_seconds: int = 300,
    network_read: bool = False,
    ws: bool = False,
    duration_seconds: int | None = None,
    info_client: InfoClientLike | None = None,
    max_leaders: int | None = None,
) -> CopyRunReport:
    started = utc_now()
    initialize_database(config)
    ledger = ResearchHistoryLedger(config.runtime_root)
    ledger.record_event("COPY_RUN_STARTED", {"interval_seconds": interval_seconds, "network_read": network_read})
    path = shortlist_path(config)
    if not path.exists():
        write_shortlist_report(
            LeaderboardShortlistReport(utc_now(), 5, 0, []),
            path,
        )
    entries = load_shortlist_entries(path)
    all_leaders = [entry for entry in entries if entry.status == LeaderStatus.SHORTLISTED]
    leader_limit = max(1, max_leaders or config.copy_max_leaders_per_run)
    leaders = all_leaders[:leader_limit]
    source_failures: list[str] = []
    no_trade = []
    accepted_paper_signals = []
    if not entries:
        no_trade.append(
            decision_from_reason(
                NoTradeReason.SOURCE_UNAVAILABLE,
                observed="Aucune shortlist leaderboard locale disponible.",
                context={"shortlist_path": str(path)},
            )
        )
        source_failures.append("leaderboard_shortlist_empty")
    if len(all_leaders) > leader_limit:
        no_trade.append(
            decision_from_reason(
                NoTradeReason.RATE_LIMIT_GUARD,
                observed=f"Shortlist bornee a {leader_limit} leaders sur {len(all_leaders)}.",
                context={"max_leaders_per_run": leader_limit, "total_shortlisted": len(all_leaders)},
            )
        )
    all_signals = []
    all_deltas = []
    if not network_read:
        no_trade.append(
            decision_from_reason(
                NoTradeReason.NETWORK_READ_DISABLED,
                observed="copy-run lance sans lecture reseau explicite.",
                context={"required_flag": "--network-read", "interval_seconds": interval_seconds},
            )
        )
    if ws and (duration_seconds is None or duration_seconds <= 0):
        no_trade.append(
            decision_from_reason(
                NoTradeReason.RATE_LIMIT_GUARD,
                observed="WebSocket demande sans duree bornee.",
                context={"required_flag": "--duration-seconds"},
            )
        )
    if network_read and leaders:
        info = info_client or HyperliquidInfoClient(config)
        start_ms = int((time() - max(1, interval_seconds)) * 1000)
        end_ms = int(time() * 1000)
        with get_connection(config) as conn:
            run = start_collection_run(conn)
            try:
                all_mids = info.get_all_mids()
            except Exception as exc:
                all_mids = {}
                source_failures.append(f"allMids_failed:{exc}")
                no_trade.append(
                    decision_from_reason(
                        NoTradeReason.API_RESPONSE_INVALID,
                        observed="allMids indisponible pendant copy-run.",
                        context={"error": str(exc)},
                    )
                )
            for leader in leaders:
                previous_positions = latest_previous_positions(conn, leader.wallet_address, utc_now())
                try:
                    snapshot = collect_leader_snapshot(
                        config=config,
                        conn=conn,
                        info_client=info,
                        wallet_address=leader.wallet_address,
                        start_time_ms=start_ms,
                        end_time_ms=end_ms,
                        all_mids=all_mids,
                        collection_run_id=run.run_id,
                    )
                except Exception as exc:
                    source_failures.append(f"{leader.wallet_address}:snapshot_failed:{exc}")
                    no_trade.append(
                        decision_from_reason(
                            NoTradeReason.API_RESPONSE_INVALID,
                            observed=f"Collecte /info echouee pour {leader.wallet_address}",
                            leader_wallet=leader.wallet_address,
                            context={"error": str(exc)},
                        )
                    )
                    continue
                deltas = diff_position_snapshots(
                    previous_positions,
                    snapshot.positions,
                    observed_at=snapshot.captured_at,
                    source_snapshot_id=snapshot.snapshot_id,
                    collection_run_id=snapshot.collection_run_id,
                )
                deltas = _merge_fill_evidence(deltas, snapshot)
                if not deltas and snapshot.open_orders:
                    no_trade.append(
                        decision_from_reason(
                            NoTradeReason.OPEN_ORDERS_CONTEXT_ONLY,
                            observed=f"{len(snapshot.open_orders)} openOrders observes pour {leader.wallet_address}",
                            leader_wallet=leader.wallet_address,
                        )
                    )
                enriched_deltas = [_enrich_delta(delta, snapshot.snapshot_id, snapshot.collection_run_id) for delta in deltas]
                all_deltas.extend(enriched_deltas)
                for delta in enriched_deltas:
                    insert_leader_delta(conn, delta)
                edge = _expected_edge_from_fills(snapshot.fills)
                signals, signal_no_trade = detect_signal_candidates(
                    enriched_deltas,
                    leader_expected_edge_bps=edge,
                    leader_scores={leader.wallet_address: leader.score},
                    current_mids={key.upper(): float(value) for key, value in all_mids.items() if _is_float(value)},
                    min_edge_required_bps=config.copy_min_edge_required_bps,
                )
                all_signals.extend(signals)
                no_trade.extend(signal_no_trade)
                deltas_by_hash = {delta.raw_event_hash: delta for delta in enriched_deltas if delta.raw_event_hash}
                for signal in signals:
                    insert_signal_candidate(conn, signal)
                    if signal.decision.value == "ACCEPT_PAPER":
                        accepted_paper_signals.append((signal, deltas_by_hash.get(signal.raw_event_hash), snapshot.leader_account_value))
                if snapshot.stopped_reason != "empty_response":
                    no_trade.append(
                        decision_from_reason(
                            NoTradeReason.PAGINATION_STOPPED,
                            observed=f"Pagination fills arretee pour {leader.wallet_address}: {snapshot.stopped_reason}",
                            leader_wallet=leader.wallet_address,
                            context={"stopped_reason": snapshot.stopped_reason},
                        )
                    )
            finish_collection_run(
                conn,
                run,
                status="OK" if not source_failures else "PARTIAL",
                stopped_reason="completed" if not source_failures else "source_failures",
                warnings=source_failures,
            )
            conn.commit()
        for signal, delta, leader_account_value in accepted_paper_signals:
            sizing_no_trade = _open_local_paper_from_signal(config, signal, delta, leader_account_value)
            no_trade.extend(sizing_no_trade)
    else:
        signals, signal_no_trade = detect_signal_candidates([], leader_expected_edge_bps=None)
        all_signals.extend(signals)
        no_trade.extend(signal_no_trade)
    finished = utc_now()
    report = CopyRunReport(
        started_at=started,
        finished_at=finished,
        interval_seconds=interval_seconds,
        dry_run=True,
        network_read=network_read,
        ws=ws,
        leaders_seen=len(leaders),
        deltas_seen=len(all_deltas),
        signal_candidates=all_signals,
        no_trade_decisions=no_trade,
        source_failures=source_failures,
    )
    ledger.record_event("COPY_RUN_FINISHED", {
        "leaders_seen": len(leaders),
        "deltas_seen": len(all_deltas),
        "signals_count": len(all_signals),
        "refusals_count": len(no_trade)
    })
    with get_connection(config) as conn:
        insert_shortlist_entries(conn, entries)
        for signal in all_signals:
            insert_signal_candidate(conn, signal)
        for decision in no_trade:
            insert_no_trade_decision(conn, decision)
        conn.commit()
    write_no_trade_reports(no_trade, config.reports_dir)
    return report


def _enrich_delta(delta, source_snapshot_id: str, collection_run_id: str):
    return delta.__class__(
        delta_id=delta.delta_id,
        leader_wallet=delta.leader_wallet,
        coin=delta.coin,
        action_type=delta.action_type,
        observed_at=delta.observed_at,
        previous_size=delta.previous_size,
        current_size=delta.current_size,
        leader_reference_price=delta.leader_reference_price,
        leader_fill_time=delta.leader_fill_time,
        raw_event_hash=delta.raw_event_hash,
        source_snapshot_id=source_snapshot_id,
        collection_run_id=collection_run_id,
        warnings=delta.warnings,
    )


def _merge_fill_evidence(deltas: list[LeaderDelta], snapshot) -> list[LeaderDelta]:
    """Prefer concrete fill evidence when it matches a position delta."""

    current_by_coin = {position.coin.upper(): position.signed_size for position in snapshot.positions}
    fill_deltas: list[LeaderDelta] = []
    for fill in snapshot.fills:
        action, warnings = classify_fill_delta(fill, current_by_coin.get(fill.coin.upper()))
        if action == DeltaAction.UNKNOWN:
            fill_deltas.append(
                LeaderDelta(
                    delta_id=f"delta:{stable_hash(f'{fill.raw_id}:{snapshot.snapshot_id}:unknown')[:24]}",
                    leader_wallet=fill.wallet_address,
                    coin=fill.coin,
                    action_type=action,
                    observed_at=fill.timestamp or snapshot.captured_at,
                    leader_reference_price=fill.price,
                    leader_fill_time=fill.timestamp,
                    raw_event_hash=fill.raw_id or stable_hash(f"{fill.wallet_address}:{fill.coin}:{fill.timestamp}:{fill.price}"),
                    source_snapshot_id=snapshot.snapshot_id,
                    collection_run_id=snapshot.collection_run_id,
                    warnings=warnings,
                )
            )
            continue
        fill_deltas.append(
            LeaderDelta(
                delta_id=f"delta:{stable_hash(f'{fill.raw_id}:{snapshot.snapshot_id}:{action.value}')[:24]}",
                leader_wallet=fill.wallet_address,
                coin=fill.coin,
                action_type=action,
                observed_at=fill.timestamp or snapshot.captured_at,
                current_size=current_by_coin.get(fill.coin.upper()),
                leader_reference_price=fill.price,
                leader_fill_time=fill.timestamp,
                raw_event_hash=fill.raw_id or stable_hash(f"{fill.wallet_address}:{fill.coin}:{fill.timestamp}:{fill.price}"),
                source_snapshot_id=snapshot.snapshot_id,
                collection_run_id=snapshot.collection_run_id,
                warnings=warnings,
            )
        )
    fill_keys = {
        (delta.leader_wallet.lower(), delta.coin.upper(), delta.action_type.value)
        for delta in fill_deltas
        if delta.action_type != DeltaAction.UNKNOWN
    }
    merged = [
        delta
        for delta in deltas
        if (delta.leader_wallet.lower(), delta.coin.upper(), delta.action_type.value) not in fill_keys
    ]
    return [*merged, *fill_deltas]


def _expected_edge_from_fills(fills) -> float | None:
    edge_values: list[float] = []
    for fill in fills:
        if fill.closed_pnl is None or fill.price in (None, 0) or fill.size in (None, 0):
            continue
        notional = abs(float(fill.price) * float(fill.size))
        if notional <= 0:
            continue
        edge_values.append(float(fill.closed_pnl) / notional * 10_000)
    if len(edge_values) < 3:
        return None
    average = sum(edge_values) / len(edge_values)
    return max(-100.0, min(100.0, average))


def _is_float(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _open_local_paper_from_signal(config: AppConfig, signal, delta=None, leader_account_value: float | None = None) -> list:
    if signal.current_mid is None:
        return [
            decision_from_reason(
                NoTradeReason.LEADER_POSITION_NOTIONAL_UNMEASURABLE,
                observed=f"{signal.action_type.value} {signal.coin} sans prix courant.",
                leader_wallet=signal.leader_wallet,
                coin=signal.coin,
                candidate_id=signal.candidate_id,
            )
        ]
    sizing = calculate_paper_copy_sizing(
        CopySizingInput(
            leader_wallet=signal.leader_wallet,
            coin=signal.coin,
            action_type=signal.action_type,
            leader_position_size=getattr(delta, "current_size", None),
            leader_reference_price=signal.current_mid,
            leader_account_value=leader_account_value,
            follower_equity=config.paper_starting_equity,
            max_notional=config.paper_max_position_notional,
            min_notional=10.0,
        )
    )
    if not sizing.accepted or sizing.requested_notional is None:
        return [
            decision_from_reason(
                reason,
                observed=f"{signal.action_type.value} {signal.coin} refuse par sizing paper proportionnel.",
                leader_wallet=signal.leader_wallet,
                coin=signal.coin,
                candidate_id=signal.candidate_id,
                context={
                    "leader_account_value": leader_account_value,
                    "leader_position_size": getattr(delta, "current_size", None),
                    "leader_position_notional": sizing.leader_position_notional,
                    "copy_ratio": sizing.copy_ratio,
                    "requested_notional": sizing.requested_notional,
                },
            )
            for reason in sizing.refusal_reasons
        ]
    side = "SELL" if signal.action_type.value.endswith("SHORT") else "BUY"
    simulator = PaperTradingSimulator(config)
    intent = simulator.create_intent_from_wallet_score(
        signal.leader_wallet,
        signal.coin,
        side,
        float(signal.current_mid),
        sizing.requested_notional,
    )
    result = simulator.open_paper_trade(intent)
    if not result.success:
        reason = (
            NoTradeReason.MAX_OPEN_PAPER_TRADES_REACHED
            if "MAX_OPEN" in result.decision.reason_code
            else NoTradeReason.SOURCE_UNAVAILABLE
        )
        return [
            decision_from_reason(
                reason,
                observed=f"{signal.action_type.value} {signal.coin} refuse par risk gate paper: {result.decision.reason_code}",
                leader_wallet=signal.leader_wallet,
                coin=signal.coin,
                candidate_id=signal.candidate_id,
                context={"risk_reason_code": result.decision.reason_code, "risk_message": result.decision.message},
            )
        ]
    return []
