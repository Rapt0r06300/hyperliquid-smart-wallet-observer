from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import time
from typing import Any

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_models import CopyRunReport, CopySizingInput, DeltaAction, LeaderDelta, LeaderStatus, NoTradeReason, SignalCandidate, stable_hash, utc_now
from hyper_smart_observer.copy_mode.copy_run_evidence import apply_runtime_leader_exits_with_evidence
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
from hyper_smart_observer.ledger.decision_ledger import DecisionLedgerEntry, DecisionLedgerExportResult, build_decision_ledger, write_decision_ledger
from hyper_smart_observer.market_signals.exporter import ScanFeaturesExportResult, write_scan_features_export
from hyper_smart_observer.market_signals.market_signal_features import MarketSignalFeatures, build_market_signal_features
from hyper_smart_observer.market_signals.volatility import compute_volatility_context
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.paper_trading.exit_engine import ExitTrigger, LeaderExitSignal
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager
from hyper_smart_observer.storage.database import get_connection, initialize_database


@dataclass(frozen=True)
class _ScanFeatureSpec:
    timestamp_ms: int
    source_ts: int | None
    wallet: str | None
    coin: str
    leader_delta: str | None = None
    leader_reference_price: float | None = None
    copy_degradation_bps: float | None = None
    edge_remaining_bps: float | None = None


@dataclass(frozen=True)
class _PaperOpenOutcome:
    no_trade_decisions: list
    candidate_id: str | None = None
    paper_intent_id: str | None = None
    paper_trade_id: str | None = None


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
    scan_feature_specs: list[_ScanFeatureSpec] = []
    scan_features_export: ScanFeaturesExportResult | None = None
    decision_features_by_coin: dict[str, MarketSignalFeatures] = {}
    paper_refs_by_decision_id: dict[str, dict[str, str | None]] = {}
    exit_ledger_entries: list[DecisionLedgerEntry] = []
    pending_exit_signals: list[LeaderExitSignal] = []
    collection_run_id: str | None = None
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
    if ws:
        ws_report = WebSocketManager(config).qa_readiness(
            _ws_subscriptions_for_leaders(leaders),
            dry_run=True,
            duration_seconds=duration_seconds,
        )
        if ws_report.fallback_to_rest_polling:
            source_failures.append(f"ws_fallback:{ws_report.stopped_reason}")
            no_trade.append(
                decision_from_reason(
                    NoTradeReason.WEBSOCKET_LIMIT_GUARD,
                    observed="Plan WebSocket read-only bascule vers polling REST borne.",
                    context={
                        "stopped_reason": ws_report.stopped_reason,
                        "subscriptions": ws_report.subscription_count,
                        "unique_users": ws_report.unique_user_count,
                        "warnings": ws_report.warnings,
                    },
                )
            )
    if network_read and leaders:
        info = info_client or HyperliquidInfoClient(config)
        start_ms = int((time() - max(1, interval_seconds)) * 1000)
        end_ms = int(time() * 1000)
        with get_connection(config) as conn:
            run = start_collection_run(conn)
            collection_run_id = run.run_id
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
            l2_book_cache: dict[str, Any] = {}
            candle_cache: dict[str, Any] = {}
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
                # Build per-coin market features from real allMids + l2Book so the
                # gates (liquidity/spread/mid) actually drive the decision at runtime.
                active_coins = sorted({delta.coin.upper() for delta in enriched_deltas})
                market_features_by_coin = _market_features_by_coin(
                    info_client=info,
                    all_mids=all_mids,
                    coins=active_coins,
                    l2_cache=l2_book_cache,
                    candle_cache=candle_cache,
                    source_failures=source_failures,
                )
                decision_features_by_coin.update(market_features_by_coin)
                entry_deltas = [delta for delta in enriched_deltas if not _is_exit_delta(delta)]
                exit_deltas = [delta for delta in enriched_deltas if _is_exit_delta(delta)]
                exit_signals = _leader_exit_signals_from_deltas(exit_deltas, market_features_by_coin)
                if exit_signals:
                    pending_exit_signals.extend(exit_signals)
                signals, signal_no_trade = detect_signal_candidates(
                    entry_deltas,
                    leader_expected_edge_bps=edge,
                    leader_scores={leader.wallet_address: leader.score},
                    current_mids={key.upper(): float(value) for key, value in all_mids.items() if _is_float(value)},
                    market_features=market_features_by_coin,
                    min_edge_required_bps=config.copy_min_edge_required_bps,
                    min_liquidity_score=config.copy_min_liquidity_score,
                )
                all_signals.extend(signals)
                no_trade.extend(signal_no_trade)
                scan_feature_specs.extend(_scan_feature_specs_from_snapshot(snapshot, end_ms))
                scan_feature_specs.extend(_scan_feature_specs_from_signals(signals, end_ms))
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
            scan_features_export = _write_runtime_scan_features_export(
                config=config,
                info_client=info,
                run_id=run.run_id,
                specs=scan_feature_specs,
                all_mids=all_mids,
                candle_cache=candle_cache,
                source_failures=source_failures,
            )
            finish_collection_run(
                conn,
                run,
                status="OK" if not source_failures else "PARTIAL",
                stopped_reason="completed" if not source_failures else "source_failures",
                warnings=source_failures,
            )
            conn.commit()
        if pending_exit_signals:
            exit_evidence = apply_runtime_leader_exits_with_evidence(
                PaperTradingSimulator(config),
                pending_exit_signals,
                reports_dir=config.reports_dir,
                run_id=collection_run_id or f"copy-run:{started.isoformat()}",
                features_by_coin=decision_features_by_coin,
                write_ledger=False,
            )
            exit_ledger_entries.extend(exit_evidence.ledger_entries)
            no_trade.extend(_no_trade_from_exit_ledger(exit_evidence.ledger_entries))
        for signal, delta, leader_account_value in accepted_paper_signals:
            outcome = _open_local_paper_from_signal(config, signal, delta, leader_account_value)
            no_trade.extend(outcome.no_trade_decisions)
            if outcome.candidate_id and (outcome.paper_intent_id or outcome.paper_trade_id):
                paper_refs_by_decision_id[outcome.candidate_id] = {
                    "paper_intent_id": outcome.paper_intent_id,
                    "paper_trade_id": outcome.paper_trade_id,
                }
    else:
        signals, signal_no_trade = detect_signal_candidates([], leader_expected_edge_bps=None)
        all_signals.extend(signals)
        no_trade.extend(signal_no_trade)
    finished = utc_now()
    ledger_run_id = collection_run_id or f"copy-run:{started.isoformat()}"
    decision_ledger_export = _write_decision_ledger_export(
        config=config,
        run_id=ledger_run_id,
        signals=all_signals,
        no_trade=no_trade,
        features_by_coin=decision_features_by_coin,
        paper_refs_by_decision_id=paper_refs_by_decision_id,
        extra_entries=exit_ledger_entries,
    )
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
        scan_features_rows=scan_features_export.rows if scan_features_export else 0,
        scan_features_json_path=str(scan_features_export.json_path) if scan_features_export else None,
        scan_features_csv_path=str(scan_features_export.csv_path) if scan_features_export else None,
        decision_ledger_entries=decision_ledger_export.entries if decision_ledger_export else 0,
        decision_ledger_json_path=str(decision_ledger_export.json_path) if decision_ledger_export else None,
        decision_ledger_csv_path=str(decision_ledger_export.csv_path) if decision_ledger_export else None,
    )
    with get_connection(config) as conn:
        insert_shortlist_entries(conn, entries)
        for signal in all_signals:
            insert_signal_candidate(conn, signal)
        for decision in no_trade:
            insert_no_trade_decision(conn, decision)
        conn.commit()
    write_no_trade_reports(no_trade, config.reports_dir)
    return report


def _write_decision_ledger_export(
    *,
    config: AppConfig,
    run_id: str,
    signals: list[SignalCandidate],
    no_trade: list,
    features_by_coin: dict[str, MarketSignalFeatures],
    paper_refs_by_decision_id: dict[str, dict[str, str | None]] | None = None,
    extra_entries: list[DecisionLedgerEntry] | None = None,
) -> DecisionLedgerExportResult | None:
    entries = build_decision_ledger(
        signals,
        no_trade,
        features_by_coin,
        run_id=run_id,
        paper_refs_by_decision_id=paper_refs_by_decision_id,
    )
    entries.extend(extra_entries or [])
    if not entries:
        return None
    return write_decision_ledger(entries, Path(config.reports_dir) / "decision_ledger", run_id=run_id)


def _is_exit_delta(delta: LeaderDelta) -> bool:
    return delta.action_type in {DeltaAction.REDUCE, DeltaAction.CLOSE_LONG, DeltaAction.CLOSE_SHORT}


def _ws_subscriptions_for_leaders(leaders) -> list[Subscription]:
    subscriptions: list[Subscription] = []
    for entry in leaders:
        wallet = getattr(entry, "wallet_address", None)
        if not wallet:
            continue
        subscriptions.append(Subscription(StreamType.USER_FILLS, user=wallet))
        subscriptions.append(Subscription(StreamType.CLEARINGHOUSE_STATE, user=wallet))
    return subscriptions


def _leader_exit_signals_from_deltas(
    deltas: list[LeaderDelta],
    features_by_coin: dict[str, MarketSignalFeatures],
) -> list[LeaderExitSignal]:
    signals: list[LeaderExitSignal] = []
    for delta in deltas:
        feature = features_by_coin.get(delta.coin.upper())
        current_mid = getattr(feature, "current_mid", None)
        trigger = ExitTrigger.LEADER_REDUCE if delta.action_type == DeltaAction.REDUCE else ExitTrigger.LEADER_CLOSE
        signals.append(
            LeaderExitSignal(
                coin=delta.coin,
                trigger=trigger,
                exit_reference_price=delta.leader_reference_price or current_mid,
                wallet_address=delta.leader_wallet,
                leader_prev_size=delta.previous_size,
                leader_curr_size=delta.current_size,
            )
        )
    return signals


def _no_trade_from_exit_ledger(entries: list[DecisionLedgerEntry]) -> list:
    out = []
    for entry in entries:
        if entry.decision_type != "PAPER_EXIT_NO_TRADE":
            continue
        reason_value = entry.reason_codes[0] if entry.reason_codes else NoTradeReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE.value
        try:
            reason = NoTradeReason(reason_value)
        except ValueError:
            reason = NoTradeReason.SOURCE_UNAVAILABLE
        out.append(
            decision_from_reason(
                reason,
                observed=f"Sortie leader {entry.exit_trigger or 'EXIT'} {entry.coin} non appliquee.",
                leader_wallet=entry.wallet or None,
                coin=entry.coin,
                context={
                    "decision_ledger_id": entry.decision_id,
                    "paper_trade_id": entry.paper_trade_id,
                    "exit_reference_price": entry.exit_reference_price,
                },
            )
        )
    return out


def _scan_feature_specs_from_snapshot(snapshot, source_ts: int) -> list[_ScanFeatureSpec]:
    timestamp_ms = _datetime_to_ms(snapshot.captured_at)
    specs: list[_ScanFeatureSpec] = []
    coins = {
        *(position.coin.upper() for position in snapshot.positions if position.coin),
        *(fill.coin.upper() for fill in snapshot.fills if fill.coin),
        *(_coin_from_order(order) for order in snapshot.open_orders),
        *(_coin_from_order(order) for order in snapshot.frontend_open_orders),
    }
    for coin in sorted(coin for coin in coins if coin):
        specs.append(
            _ScanFeatureSpec(
                timestamp_ms=timestamp_ms,
                source_ts=source_ts,
                wallet=snapshot.wallet_address,
                coin=coin,
            )
        )
    return specs


def _scan_feature_specs_from_signals(signals: list[SignalCandidate], source_ts: int) -> list[_ScanFeatureSpec]:
    return [
        _ScanFeatureSpec(
            timestamp_ms=_datetime_to_ms(signal.observed_at),
            source_ts=source_ts,
            wallet=signal.leader_wallet,
            coin=signal.coin,
            leader_delta=signal.action_type.value,
            leader_reference_price=signal.leader_reference_price,
            copy_degradation_bps=signal.copy_degradation_bps,
            edge_remaining_bps=signal.edge_remaining_bps,
        )
        for signal in signals
    ]


def _market_features_by_coin(
    *,
    info_client: InfoClientLike,
    all_mids: dict[str, Any],
    coins: list[str],
    l2_cache: dict[str, Any],
    source_failures: list[str],
    candle_cache: dict[str, Any] | None = None,
    max_coins: int = 20,
) -> dict[str, MarketSignalFeatures]:
    """Build per-coin MarketSignalFeatures from allMids + l2Book (read-only).

    l2Book is fetched at most once per coin per run (rate-limit aware). A
    missing/invalid l2Book collapses to an empty book => liquidity_score 0 and
    degraded data_quality, so the gates emit a NoTradeDecision (never a
    PaperIntent). allMids still provides current_mid provenance.
    """
    get_l2_book = getattr(info_client, "get_l2_book", None)
    get_candle = getattr(info_client, "get_candle_snapshot", None)
    candle_cache = candle_cache if candle_cache is not None else {}
    now_ms = int(utc_now().timestamp() * 1000)
    features: dict[str, MarketSignalFeatures] = {}
    for coin in list(coins)[:max_coins]:
        key = coin.upper()
        book = l2_cache.get(key)
        if book is None:
            if not callable(get_l2_book):
                source_failures.append("l2Book_unavailable:client_missing")
                book = {}
            else:
                try:
                    raw = get_l2_book(key)
                except Exception as exc:  # read-only: degrade safely, never raise into decisions
                    source_failures.append(f"l2Book_failed:{key}:{exc}")
                    raw = None
                if isinstance(raw, dict):
                    book = raw
                else:
                    if raw is not None:
                        source_failures.append(f"l2Book_invalid:{key}")
                    book = {}
            l2_cache[key] = book
        # Volatility from candleSnapshot (read-only, cached once per run).
        # Absent => None / MISSING in MarketSignalFeatures, never fabricated.
        volatility = candle_cache.get(key, "MISS")
        if volatility == "MISS":
            volatility = None
            if callable(get_candle):
                try:
                    volatility = compute_volatility_context(get_candle(key))
                except Exception as exc:  # read-only: degrade safely
                    source_failures.append(f"candle_failed:{key}:{exc}")
                    volatility = None
            candle_cache[key] = volatility
        health = "OK" if isinstance(book, dict) and book.get("levels") else "DEGRADED"
        features[key] = build_market_signal_features(
            timestamp_ms=now_ms,
            source_ts=now_ms,
            symbol=key,
            l2_book=book,
            all_mids=all_mids,
            volatility_context=volatility,
            source_health=health,
        )
    return features


def _write_runtime_scan_features_export(
    *,
    config: AppConfig,
    info_client: InfoClientLike,
    run_id: str,
    specs: list[_ScanFeatureSpec],
    all_mids: dict[str, Any],
    candle_cache: dict[str, Any] | None = None,
    source_failures: list[str],
) -> ScanFeaturesExportResult:
    output_dir = Path(config.reports_dir) / "scan_features"
    unique_specs = _dedupe_scan_feature_specs(specs)
    get_l2_book = getattr(info_client, "get_l2_book", None)
    if not unique_specs or not callable(get_l2_book):
        if unique_specs:
            source_failures.append("l2Book_unavailable:client_missing")
        return write_scan_features_export([], output_dir, run_id=run_id)

    l2_by_coin: dict[str, dict[str, Any]] = {}
    for coin in sorted({spec.coin.upper() for spec in unique_specs}):
        try:
            raw_book = get_l2_book(coin)
        except Exception as exc:
            source_failures.append(f"l2Book_failed:{coin}:{exc}")
            continue
        if isinstance(raw_book, dict):
            l2_by_coin[coin] = raw_book
        else:
            source_failures.append(f"l2Book_invalid:{coin}")

    features: list[MarketSignalFeatures] = []
    candle_cache = candle_cache or {}
    for spec in unique_specs:
        l2_book = l2_by_coin.get(spec.coin.upper())
        if l2_book is None:
            continue
        volatility = candle_cache.get(spec.coin.upper())
        if volatility == "MISS":
            volatility = None
        features.append(
            build_market_signal_features(
                timestamp_ms=spec.timestamp_ms,
                source_ts=spec.source_ts,
                symbol=spec.coin,
                wallet=spec.wallet,
                l2_book=l2_book,
                all_mids=all_mids,
                leader_delta=spec.leader_delta,
                leader_reference_price=spec.leader_reference_price,
                copy_degradation_bps=spec.copy_degradation_bps,
                edge_remaining_bps=spec.edge_remaining_bps,
                volatility_context=volatility,
                source_health="OK",
            )
        )
    return write_scan_features_export(features, output_dir, run_id=run_id)


def _dedupe_scan_feature_specs(specs: list[_ScanFeatureSpec]) -> list[_ScanFeatureSpec]:
    unique: list[_ScanFeatureSpec] = []
    seen: set[tuple[str | None, str, str | None, float | None]] = set()
    for spec in specs:
        key = (
            spec.wallet.lower() if spec.wallet else None,
            spec.coin.upper(),
            spec.leader_delta,
            spec.edge_remaining_bps,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def _coin_from_order(order: dict[str, Any]) -> str:
    return str(order.get("coin") or "").upper().strip()


def _datetime_to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


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
                    previous_size=fill.start_position,
                    current_size=current_by_coin.get(fill.coin.upper()),
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
                previous_size=fill.start_position,
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


def _open_local_paper_from_signal(
    config: AppConfig,
    signal,
    delta=None,
    leader_account_value: float | None = None,
) -> _PaperOpenOutcome:
    if signal.current_mid is None:
        return _PaperOpenOutcome(
            [
                decision_from_reason(
                    NoTradeReason.LEADER_POSITION_NOTIONAL_UNMEASURABLE,
                    observed=f"{signal.action_type.value} {signal.coin} sans prix courant.",
                    leader_wallet=signal.leader_wallet,
                    coin=signal.coin,
                    candidate_id=signal.candidate_id,
                )
            ],
            candidate_id=signal.candidate_id,
        )
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
        return _PaperOpenOutcome(
            [
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
            ],
            candidate_id=signal.candidate_id,
        )
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
        return _PaperOpenOutcome(
            [
                decision_from_reason(
                    reason,
                    observed=f"{signal.action_type.value} {signal.coin} refuse par risk gate paper: {result.decision.reason_code}",
                    leader_wallet=signal.leader_wallet,
                    coin=signal.coin,
                    candidate_id=signal.candidate_id,
                    context={"risk_reason_code": result.decision.reason_code, "risk_message": result.decision.message},
                )
            ],
            candidate_id=signal.candidate_id,
            paper_intent_id=result.intent.intent_id,
        )
    return _PaperOpenOutcome(
        [],
        candidate_id=signal.candidate_id,
        paper_intent_id=result.intent.intent_id,
        paper_trade_id=result.trade.trade_id if result.trade else None,
    )
