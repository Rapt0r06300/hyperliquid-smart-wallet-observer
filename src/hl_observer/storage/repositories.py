from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from hl_observer.storage.models import (
    ApiHealth,
    AutoWatchlist,
    CoinOpportunity,
    CollectionItem,
    CollectionRun,
    Fill,
    MarketMetric,
    MarketSnapshot,
    MarketUniverseModel,
    OpenOrder,
    OrderbookSnapshot,
    Position,
    PositionDeltaModel,
    RawEvent,
    RejectedSignal,
    Wallet,
    WalletActivitySummary,
    WalletBackfillRun,
    WalletCandidateModel,
    WalletCandidateScoreModel,
    WalletCoinProfileModel,
    WalletCoinScoreModel,
    WalletDiscoveryRun,
    WalletDiscoverySourceModel,
    WalletSnapshot,
    EdgeMetric,
)
from hl_observer.signals.position_delta_detector import PositionDelta
from hl_observer.utils.time import now_ms
from hl_observer.wallets.activity_summary import WalletActivitySummaryRecord
from hl_observer.wallets.auto_watchlist import add_to_auto_watchlist
from hl_observer.wallets.discovery_scoring import WalletCandidateScore
from hl_observer.wallets.discovery_sources import WalletDiscoveryCandidate, WalletDiscoverySourceResult
from hl_observer.markets.coin_metrics import CoinOpportunityRecord, MarketMetricRecord
from hl_observer.markets.universe import MarketUniverseItem
from hl_observer.wallets.per_coin_scoring import WalletCoinScore
from hl_observer.wallets.wallet_coin_profile import WalletCoinProfile
from hl_observer.wallets.position_delta_engine import PositionDeltaRecord
from hl_observer.wallets.position_rebuilder import RebuiltPosition, rebuild_positions_from_fills


def stable_payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _extract_orderbook_stats(book: dict[str, Any]) -> tuple[float | None, float | None]:
    levels = book.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return None, None
    bids = levels[0] if isinstance(levels[0], list) else []
    asks = levels[1] if isinstance(levels[1], list) else []

    def level_price(level: Any) -> float | None:
        return _safe_float(level.get("px")) if isinstance(level, dict) else None

    def level_depth(level: Any) -> float:
        if not isinstance(level, dict):
            return 0.0
        price = _safe_float(level.get("px")) or 0.0
        size = _safe_float(level.get("sz")) or 0.0
        return price * size

    best_bid = level_price(bids[0]) if bids else None
    best_ask = level_price(asks[0]) if asks else None
    spread_bps = None
    if best_bid and best_ask and best_bid > 0:
        mid = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / mid * 10000 if mid > 0 else None
    depth_usdc = sum(level_depth(level) for level in bids[:10]) + sum(level_depth(level) for level in asks[:10])
    return depth_usdc, spread_bps


def _detailed_delta_type(action: str, previous_side: str | None, new_side: str | None) -> str:
    if action == "OPEN" and new_side:
        return f"open_{new_side.lower()}"
    if action == "ADD" and new_side:
        return f"add_{new_side.lower()}"
    if action == "REDUCE" and previous_side:
        return f"reduce_{previous_side.lower()}"
    if action == "CLOSE" and previous_side:
        return f"close_{previous_side.lower()}"
    if action == "FLIP" and previous_side and new_side:
        return f"flip_{previous_side.lower()}_to_{new_side.lower()}"
    return action.lower()


class CollectionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._seen_fill_hashes: set[str] = set()
        self._seen_delta_hashes: set[str] = set()

    def create_collection_run(
        self,
        *,
        mode: str,
        wallets_count: int,
        coins_count: int,
        notes: str | None = None,
    ) -> CollectionRun:
        run = CollectionRun(
            started_at_ms=now_ms(),
            finished_at_ms=None,
            mode=mode,
            success=False,
            errors_count=0,
            wallets_count=wallets_count,
            coins_count=coins_count,
            notes=notes,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_collection_run(self, run: CollectionRun, *, success: bool, errors_count: int) -> CollectionRun:
        run.finished_at_ms = now_ms()
        run.success = success
        run.errors_count = errors_count
        self.session.add(run)
        return run

    def create_wallet_backfill_run(
        self,
        *,
        wallet_address: str,
        start_ms: int | None,
        end_ms: int | None,
        notes: str | None = None,
    ) -> WalletBackfillRun:
        run = WalletBackfillRun(
            wallet_address=wallet_address,
            started_at_ms=now_ms(),
            finished_at_ms=None,
            start_ms=start_ms,
            end_ms=end_ms,
            status="RUNNING",
            fills_count=0,
            open_orders_count=0,
            deltas_count=0,
            errors_count=0,
            confidence_score=0.0,
            notes=notes,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_wallet_backfill_run(
        self,
        run: WalletBackfillRun,
        *,
        status: str,
        fills_count: int,
        open_orders_count: int,
        deltas_count: int,
        errors_count: int,
        confidence_score: float,
        notes: str | None = None,
    ) -> WalletBackfillRun:
        run.finished_at_ms = now_ms()
        run.status = status
        run.fills_count = fills_count
        run.open_orders_count = open_orders_count
        run.deltas_count = deltas_count
        run.errors_count = errors_count
        run.confidence_score = confidence_score
        if notes is not None:
            run.notes = notes
        self.session.add(run)
        return run

    def add_collection_item(
        self,
        *,
        run_id: int,
        item_type: str,
        wallet_address: str | None = None,
        coin: str | None = None,
        status: str = "pending",
        error_message: str | None = None,
    ) -> CollectionItem:
        item = CollectionItem(
            run_id=run_id,
            item_type=item_type,
            wallet_address=wallet_address,
            coin=coin,
            status=status,
            error_message=error_message,
        )
        self.session.add(item)
        return item

    def store_raw_event(
        self,
        *,
        source: str,
        endpoint: str,
        request_type: str,
        request_payload: dict[str, Any],
        response_payload: Any,
        wallet_address: str | None = None,
        coin: str | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> RawEvent:
        fetched_at_ms = now_ms()
        response_hash = stable_payload_hash(response_payload)
        event = RawEvent(
            source=source,
            endpoint=endpoint,
            request_type=request_type,
            wallet_address=wallet_address,
            coin=coin,
            request_payload_json=request_payload,
            response_payload_json=response_payload,
            response_hash=response_hash,
            fetched_at_ms=fetched_at_ms,
            success=success,
            error_message=error_message,
            event_type=request_type,
            wallet=wallet_address,
            exchange_ts=None,
            local_received_ts=fetched_at_ms,
            payload_json={"request": request_payload, "response": response_payload},
            payload_hash=response_hash,
        )
        self.session.add(event)
        return event

    def store_market_snapshot_from_all_mids(self, response_payload: dict[str, Any]) -> MarketSnapshot:
        snapshot = MarketSnapshot(source="allMids", exchange_ts=None, raw_json=response_payload)
        self.session.add(snapshot)
        return snapshot

    def store_orderbook_snapshot(self, coin: str, response_payload: dict[str, Any]) -> OrderbookSnapshot:
        depth_usdc, spread_bps = _extract_orderbook_stats(response_payload)
        snapshot = OrderbookSnapshot(
            coin=coin.upper(),
            exchange_ts=None,
            depth_usdc=depth_usdc,
            spread_bps=spread_bps,
            raw_json=response_payload,
        )
        self.session.add(snapshot)
        return snapshot

    def store_market_universe_item(self, item: MarketUniverseItem) -> MarketUniverseModel:
        existing = (
            self.session.query(MarketUniverseModel)
            .filter(MarketUniverseModel.coin == item.coin.upper(), MarketUniverseModel.source == item.source)
            .order_by(MarketUniverseModel.id.desc())
            .first()
        )
        timestamp = now_ms()
        if existing is None:
            model = MarketUniverseModel(
                coin=item.coin.upper(),
                source=item.source,
                is_active=item.is_active,
                is_spot=item.is_spot,
                first_seen_ms=timestamp,
                last_seen_ms=timestamp,
                mid_price=item.mid_price,
                notes=item.notes,
            )
            self.session.add(model)
            return model
        existing.is_active = item.is_active
        existing.is_spot = item.is_spot
        existing.last_seen_ms = timestamp
        existing.mid_price = item.mid_price
        existing.notes = item.notes
        self.session.add(existing)
        return existing

    def store_market_metric(self, metric: MarketMetricRecord) -> MarketMetric:
        model = MarketMetric(
            coin=metric.coin.upper(),
            computed_at_ms=metric.computed_at_ms,
            mid_price=metric.mid_price,
            spread_bps=metric.spread_bps,
            depth_usdc=metric.depth_usdc,
            volume_hint_usdc=metric.volume_hint_usdc,
            open_interest_hint_usdc=metric.open_interest_hint_usdc,
            funding_hint=metric.funding_hint,
            liquidity_score=metric.liquidity_score,
            is_scannable=metric.is_scannable,
            rejection_reason=metric.rejection_reason,
        )
        self.session.add(model)
        return model

    def ensure_wallet(self, wallet_address: str, *, label: str | None = None, status: str = "observed") -> Wallet:
        wallet = self.session.get(Wallet, wallet_address)
        if wallet is None:
            wallet = Wallet(address=wallet_address, label=label, status=status)
            self.session.add(wallet)
        elif status and wallet.status == "candidate":
            wallet.status = status
        return wallet

    def store_wallet_snapshot(
        self,
        wallet_address: str,
        response_payload: dict[str, Any],
        *,
        exchange_ts: int | None = None,
    ) -> WalletSnapshot:
        snapshot = WalletSnapshot(
            wallet_address=wallet_address,
            exchange_ts=exchange_ts,
            raw_json=response_payload,
        )
        self.session.add(snapshot)
        return snapshot

    def store_fills(self, wallet_address: str, response_payload: list[dict[str, Any]]) -> list[Fill]:
        stored: list[Fill] = []
        for fill in response_payload:
            coin = str(fill.get("coin") or fill.get("coinName") or "UNKNOWN")
            exchange_ts = int(fill.get("time") or fill.get("timestamp") or 0)
            fill_hash = stable_payload_hash({"wallet": wallet_address, "fill": fill})
            if fill_hash in self._seen_fill_hashes:
                continue
            existing = self.session.query(Fill.id).filter(Fill.fill_hash == fill_hash).first()
            if existing is not None:
                self._seen_fill_hashes.add(fill_hash)
                continue
            model = Fill(
                wallet_address=wallet_address,
                coin=coin.upper(),
                exchange_ts=exchange_ts,
                side=str(fill.get("side")) if fill.get("side") is not None else None,
                price=_safe_float(_first_present(fill, "px", "price")),
                size=_safe_float(_first_present(fill, "sz", "size")),
                fill_hash=fill_hash,
                oid=str(fill.get("oid")) if fill.get("oid") is not None else None,
                tid=str(fill.get("tid")) if fill.get("tid") is not None else None,
                direction=str(fill.get("dir")) if fill.get("dir") is not None else None,
                start_position=_safe_float(_first_present(fill, "startPosition", "start_position")),
                closed_pnl=_safe_float(_first_present(fill, "closedPnl", "closed_pnl")),
                fee=_safe_float(fill.get("fee")),
                raw_json=fill,
            )
            self.session.add(model)
            self._seen_fill_hashes.add(fill_hash)
            stored.append(model)
        return stored

    def store_open_orders(self, wallet_address: str, response_payload: list[dict[str, Any]]) -> list[OpenOrder]:
        stored: list[OpenOrder] = []
        for order in response_payload:
            model = OpenOrder(
                wallet_address=wallet_address,
                coin=str(order.get("coin") or "UNKNOWN"),
                oid=str(order.get("oid")) if order.get("oid") is not None else None,
                cloid=str(order.get("cloid")) if order.get("cloid") is not None else None,
                raw_json=order,
            )
            self.session.add(model)
            stored.append(model)
        return stored

    def store_candles(self, coin: str, response_payload: list[dict[str, Any]]) -> None:
        # Candle normalization arrives in a later batch; raw_events keeps replay-safe payloads now.
        _ = (coin, response_payload)

    def store_api_health(
        self,
        *,
        service: str,
        ok: bool,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> ApiHealth:
        health = ApiHealth(service=service, ok=ok, latency_ms=latency_ms, error=error)
        self.session.add(health)
        return health

    def store_position(self, position: RebuiltPosition) -> Position:
        model = Position(
            wallet_address=position.wallet_address,
            coin=position.coin.upper(),
            side=position.side.value,
            size=position.size,
            entry_price=position.entry_px_estimated,
            entry_px_estimated=position.entry_px_estimated,
            last_px=position.last_px,
            notional_usdc=position.notional_usdc,
            source=position.source,
            confidence_score=position.confidence_score,
            opened_at_ms=position.opened_at_ms,
            updated_at_ms=position.updated_at_ms,
            status=position.status,
            raw_json={
                "notes": position.notes,
                "raw": position.raw,
            },
        )
        self.session.add(model)
        return model

    def store_position_delta(self, delta: PositionDelta | PositionDeltaRecord) -> PositionDeltaModel | None:
        if isinstance(delta, PositionDeltaRecord):
            wallet_address = delta.wallet_address
            coin = delta.coin.upper()
            previous_size = delta.previous_size
            current_size = delta.new_size
            exchange_ts = delta.exchange_ts
            raw = delta.raw
            delta_hash = stable_payload_hash(
                {
                    "wallet": wallet_address,
                    "coin": coin,
                    "exchange_ts": exchange_ts,
                    "previous_size": previous_size,
                    "new_size": current_size,
                    "raw": raw,
                }
            )
            previous_side = delta.previous_side.value
            new_side = delta.new_side.value
            action = delta.action.value
            delta_notional = delta.delta_notional_usdc
            source_event_id = delta.source_event_id
            confidence_score = delta.confidence_score
            detected_at_ms = now_ms()
            delta_type = _detailed_delta_type(action, previous_side, new_side)
            confidence = (
                "high" if confidence_score >= 0.85 else "medium" if confidence_score >= 0.5 else "low"
            )
        else:
            wallet_address = delta.wallet
            coin = delta.coin.upper()
            previous_size = delta.previous_size
            current_size = delta.current_size
            exchange_ts = delta.exchange_ts
            raw = delta.raw
            delta_hash = stable_payload_hash(
                {
                    "wallet": wallet_address,
                    "coin": coin,
                    "exchange_ts": exchange_ts,
                    "previous_size": previous_size,
                    "current_size": current_size,
                    "raw": raw,
                }
            )
            previous_side = None
            new_side = None
            action = delta.delta_type.upper()
            delta_notional = abs(delta.delta_size) * delta.price if delta.price is not None else None
            source_event_id = None
            confidence_score = 0.95 if delta.confidence == "high" else 0.65 if delta.confidence == "medium" else 0.35
            detected_at_ms = now_ms()
            delta_type = delta.delta_type
            confidence = delta.confidence

        if delta_hash in self._seen_delta_hashes:
            return None
        existing = self.session.query(PositionDeltaModel.id).filter(
            PositionDeltaModel.delta_hash == delta_hash
        ).first()
        if existing is not None:
            self._seen_delta_hashes.add(delta_hash)
            return None
        model = PositionDeltaModel(
            wallet_address=wallet_address,
            coin=coin,
            previous_side=previous_side,
            new_side=new_side,
            previous_size=previous_size,
            current_size=current_size,
            new_size=current_size,
            delta_size=current_size - previous_size,
            delta_notional_usdc=delta_notional,
            action=action,
            exchange_ts=exchange_ts,
            fill_id=getattr(delta, "fill_id", None),
            source_event_id=source_event_id,
            side=getattr(delta, "side", None),
            price=getattr(delta, "price", None),
            fill_size=getattr(delta, "fill_size", None),
            delta_type=delta_type,
            confidence=confidence,
            confidence_score=confidence_score,
            detected_at_ms=detected_at_ms,
            source=getattr(delta, "source", "fills"),
            delta_hash=delta_hash,
            raw_json=raw,
        )
        self.session.add(model)
        self._seen_delta_hashes.add(delta_hash)
        return model

    def store_position_deltas(self, deltas: list[PositionDelta | PositionDeltaRecord]) -> list[PositionDeltaModel]:
        stored: list[PositionDeltaModel] = []
        for delta in deltas:
            model = self.store_position_delta(delta)
            if model is not None:
                stored.append(model)
        return stored

    def get_fills_for_wallet(self, wallet_address: str, *, coin: str | None = None) -> list[Fill]:
        query = self.session.query(Fill).filter(Fill.wallet_address == wallet_address)
        if coin is not None:
            query = query.filter(Fill.coin == coin.upper())
        return list(query.order_by(Fill.exchange_ts.asc(), Fill.id.asc()).all())

    def rebuild_positions_from_fills(self, wallet_address: str, *, coin: str | None = None) -> list[Position]:
        fills = [fill.raw_json for fill in self.get_fills_for_wallet(wallet_address, coin=coin)]
        rebuild = rebuild_positions_from_fills(wallet_address, fills)
        return [self.store_position(position) for position in rebuild.positions]

    def get_latest_position(self, wallet_address: str, coin: str) -> Position | None:
        return (
            self.session.query(Position)
            .filter(Position.wallet_address == wallet_address, Position.coin == coin.upper())
            .order_by(Position.id.desc())
            .first()
        )

    def store_wallet_activity_summary(
        self,
        summary: WalletActivitySummaryRecord,
    ) -> WalletActivitySummary:
        model = WalletActivitySummary(
            wallet_address=summary.wallet_address,
            window_start_ms=summary.window_start_ms,
            window_end_ms=summary.window_end_ms,
            fills_count=summary.fills_count,
            coins_count=summary.coins_count,
            total_volume_estimated=summary.total_volume_estimated,
            long_actions_count=summary.long_actions_count,
            short_actions_count=summary.short_actions_count,
            open_count=summary.open_count,
            add_count=summary.add_count,
            reduce_count=summary.reduce_count,
            close_count=summary.close_count,
            flip_count=summary.flip_count,
            created_at_ms=summary.created_at_ms,
        )
        self.session.add(model)
        return model

    def store_wallet_coin_profile(self, profile: WalletCoinProfile) -> WalletCoinProfileModel:
        model = WalletCoinProfileModel(
            wallet_address=profile.wallet_address,
            coin=profile.coin.upper(),
            window=profile.window,
            computed_at_ms=profile.computed_at_ms,
            fills_count=profile.fills_count,
            deltas_count=profile.deltas_count,
            estimated_pnl_usdc=profile.estimated_pnl_usdc,
            estimated_roi_pct=profile.estimated_roi_pct,
            estimated_volume_usdc=profile.estimated_volume_usdc,
            win_rate=profile.win_rate,
            profit_factor=profile.profit_factor,
            max_drawdown_pct=profile.max_drawdown_pct,
            last_activity_ms=profile.last_activity_ms,
            copyability_score=profile.copyability_score,
            liquidity_score=profile.liquidity_score,
            toxicity_score=profile.toxicity_score,
            final_coin_score=profile.final_coin_score,
            confidence_score=profile.confidence_score,
            status=profile.status,
        )
        self.session.add(model)
        return model

    def store_wallet_coin_score(self, score: WalletCoinScore) -> WalletCoinScoreModel:
        model = WalletCoinScoreModel(
            wallet_address=score.wallet_address,
            coin=score.coin.upper(),
            computed_at_ms=now_ms(),
            performance_score=score.performance_score,
            risk_score=score.risk_score,
            consistency_score=score.consistency_score,
            copyability_score=score.copyability_score,
            liquidity_score=score.liquidity_score,
            timing_score=score.timing_score,
            toxicity_penalty=score.toxicity_penalty,
            final_score=score.final_score,
            decision=score.decision,
            reasons_json=score.reasons,
        )
        self.session.add(model)
        return model

    def store_coin_opportunity(self, opportunity: CoinOpportunityRecord) -> CoinOpportunity:
        model = CoinOpportunity(
            coin=opportunity.coin.upper(),
            computed_at_ms=now_ms(),
            wallets_active=opportunity.wallets_active,
            wallets_positive_pnl=opportunity.wallets_positive_pnl,
            wallets_positive_roi=opportunity.wallets_positive_roi,
            avg_wallet_score=opportunity.avg_wallet_score,
            best_wallet_address=opportunity.best_wallet_address,
            best_wallet_score=opportunity.best_wallet_score,
            liquidity_score=opportunity.liquidity_score,
            spread_bps=opportunity.spread_bps,
            opportunity_score=opportunity.opportunity_score,
            status=opportunity.status,
            notes=opportunity.notes,
        )
        self.session.add(model)
        return model

    def get_wallet_activity_summary(self, wallet_address: str) -> WalletActivitySummary | None:
        return (
            self.session.query(WalletActivitySummary)
            .filter(WalletActivitySummary.wallet_address == wallet_address)
            .order_by(WalletActivitySummary.id.desc())
            .first()
        )


class RawEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        *,
        source: str,
        event_type: str,
        payload: dict[str, Any],
        wallet: str | None = None,
        coin: str | None = None,
        exchange_ts: int | None = None,
    ) -> RawEvent:
        fetched_at_ms = now_ms()
        payload_hash = stable_payload_hash(payload)
        event = RawEvent(
            source=source,
            endpoint="/info",
            request_type=event_type,
            wallet_address=wallet,
            request_payload_json={},
            response_payload_json=payload,
            response_hash=payload_hash,
            fetched_at_ms=fetched_at_ms,
            success=True,
            error_message=None,
            event_type=event_type,
            wallet=wallet,
            coin=coin,
            exchange_ts=exchange_ts,
            local_received_ts=fetched_at_ms,
            payload_json=payload,
            payload_hash=payload_hash,
        )
        self.session.add(event)
        return event


class DiscoveryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_wallet_discovery_run(self, *, notes: str | None = None) -> WalletDiscoveryRun:
        run = WalletDiscoveryRun(
            started_at_ms=now_ms(),
            finished_at_ms=None,
            status="RUNNING",
            sources_attempted=0,
            candidates_found=0,
            candidates_after_filter=0,
            wallets_selected=0,
            errors_count=0,
            notes=notes,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_wallet_discovery_run(
        self,
        run: WalletDiscoveryRun,
        *,
        status: str,
        sources_attempted: int,
        candidates_found: int,
        candidates_after_filter: int,
        wallets_selected: int,
        errors_count: int,
        notes: str | None = None,
    ) -> WalletDiscoveryRun:
        run.finished_at_ms = now_ms()
        run.status = status
        run.sources_attempted = sources_attempted
        run.candidates_found = candidates_found
        run.candidates_after_filter = candidates_after_filter
        run.wallets_selected = wallets_selected
        run.errors_count = errors_count
        if notes is not None:
            run.notes = notes
        self.session.add(run)
        return run

    def store_discovery_source(
        self,
        *,
        run_id: int,
        source_result: WalletDiscoverySourceResult,
    ) -> WalletDiscoverySourceModel:
        model = WalletDiscoverySourceModel(
            run_id=run_id,
            source_name=source_result.source_name,
            source_type=source_result.source_type,
            url=source_result.url,
            reliability_score=source_result.reliability_score,
            status=source_result.status,
            candidates_found=len(source_result.candidates),
            error_message=source_result.error_message,
            fetched_at_ms=source_result.fetched_at_ms,
        )
        self.session.add(model)
        return model

    def store_wallet_candidate(
        self,
        *,
        run_id: int,
        candidate: WalletDiscoveryCandidate,
        selected_for_backfill: bool,
        rejection_reason: str | None,
    ) -> WalletCandidateModel:
        now = now_ms()
        model = WalletCandidateModel(
            run_id=run_id,
            address=candidate.address or "",
            coin=candidate.coin,
            source_name=candidate.source_name,
            source_type=candidate.source_type,
            label=candidate.label,
            external_pnl_usdc=candidate.external_pnl_usdc,
            external_roi_pct=candidate.external_roi_pct,
            external_volume_usdc=candidate.external_volume_usdc,
            external_win_rate=candidate.external_win_rate,
            external_position_usdc=candidate.external_position_usdc,
            external_unrealized_pnl=candidate.external_unrealized_pnl,
            external_funding_fee=candidate.external_funding_fee,
            first_seen_ms=candidate.first_seen_ms or now,
            last_seen_ms=candidate.last_seen_ms or now,
            raw_payload_json=candidate.raw_payload,
            confidence_score=candidate.confidence_score,
            selected_for_backfill=selected_for_backfill,
            rejection_reason=rejection_reason,
        )
        self.session.add(model)
        return model

    def store_wallet_candidate_score(
        self,
        *,
        run_id: int,
        score: WalletCandidateScore,
    ) -> WalletCandidateScoreModel:
        model = WalletCandidateScoreModel(
            wallet_address=score.wallet_address,
            coin=score.coin,
            run_id=run_id,
            pnl_positive_score=score.pnl_positive_score,
            roi_positive_score=score.roi_positive_score,
            activity_score=score.activity_score,
            recency_score=score.recency_score,
            size_score=score.size_score,
            copyability_pre_score=score.copyability_pre_score,
            source_confidence_score=score.source_confidence_score,
            final_discovery_score=score.final_discovery_score,
            decision=score.decision.value,
            reasons_json=score.reasons,
        )
        self.session.add(model)
        return model

    def add_auto_watchlist(
        self,
        *,
        wallet_address: str,
        coin: str | None = None,
        label: str | None,
        source: str,
        discovery_score: float,
        notes: str | None = None,
    ) -> AutoWatchlist:
        return add_to_auto_watchlist(
            self.session,
            wallet_address=wallet_address,
            coin=coin,
            label=label,
            source=source,
            discovery_score=discovery_score,
            notes=notes,
        )


class RejectedSignalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, *, signal_id: str, decision: str, reason: str, raw: dict[str, Any]) -> RejectedSignal:
        rejected = RejectedSignal(
            signal_id=signal_id,
            decision=decision,
            reason=reason,
            raw_json=raw,
        )
        self.session.add(rejected)
        return rejected


class EdgeMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def store_edge_metric(
        self,
        *,
        signal_id: str,
        expected_edge_bps: float,
        costs_bps: float,
        edge_remaining_bps: float,
        gain_assurance_score: float | None = None,
        freshness_factor: float | None = None,
        consistency_factor: float | None = None,
        liquidity_penalty_bps: float | None = None,
        crowding_penalty_bps: float | None = None,
        adverse_selection_bps: float | None = None,
        funding_penalty_bps: float | None = None,
        delay_cost_bps: float | None = None,
        decision: str,
    ) -> EdgeMetric:
        model = EdgeMetric(
            signal_id=signal_id,
            expected_edge_bps=expected_edge_bps,
            costs_bps=costs_bps,
            edge_remaining_bps=edge_remaining_bps,
            gain_assurance_score=gain_assurance_score,
            freshness_factor=freshness_factor,
            consistency_factor=consistency_factor,
            liquidity_penalty_bps=liquidity_penalty_bps,
            crowding_penalty_bps=crowding_penalty_bps,
            adverse_selection_bps=adverse_selection_bps,
            funding_penalty_bps=funding_penalty_bps,
            delay_cost_bps=delay_cost_bps,
            decision=decision,
        )
        self.session.add(model)
        return model
