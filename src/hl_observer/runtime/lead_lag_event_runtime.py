"""Event-driven lead-lag paper runtime.

Called synchronously from the real Binance trade collector. It owns no network
client and has no real-execution surface. Runtime state is persisted atomically
so a BBO collector restart cannot forget open paper positions or fabricate a
second fill for an already-open episode.
"""
from __future__ import annotations

import json
import math
import os
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_evidence import (
    FrozenLeadLagEvidenceError,
    load_frozen_evidence,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.paper_engine import (
    PaperDecisionResult,
    PaperEngine,
    PaperPosition,
)
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta

DEFAULT_CONFIG = Path("runtime") / "data" / "lead_lag_config_gele.json"
DEFAULT_DECISIONS = Path("runtime") / "data" / "lead_lag_event_decisions.jsonl"
DEFAULT_STATUS = Path("runtime") / "data" / "lead_lag_event_runtime_status.json"
DEFAULT_STATE = Path("runtime") / "data" / "lead_lag_event_runtime_state.json"
STATE_SCHEMA = "hypersmart.lead_lag_event_state.v1"


@dataclass(frozen=True, slots=True)
class LeadLagEventOutcome:
    event_id: str
    coin: str
    code: str
    accepted: bool = False
    latency_ms: float | None = None
    edge_remaining_bps: float | None = None
    paper_result: PaperDecisionResult | None = None


class LeadLagEventPaperRuntime:
    """Bounded fail-closed bridge from a live trade event to local paper."""

    def __init__(
        self,
        root: str | Path,
        *,
        config_path: str | Path | None = None,
        decisions_path: str | Path | None = None,
        status_path: str | Path | None = None,
        state_path: str | Path | None = None,
        paper_engine: PaperEngine | None = None,
        seen_capacity: int = 100_000,
    ) -> None:
        self.root = Path(root)
        self.config_path = Path(config_path or self.root / DEFAULT_CONFIG)
        self.decisions_path = Path(decisions_path or self.root / DEFAULT_DECISIONS)
        self.status_path = Path(status_path or self.root / DEFAULT_STATUS)
        self.state_path = Path(state_path or self.root / DEFAULT_STATE)
        self.paper_engine = paper_engine or PaperEngine()
        self._last_trade_price: dict[str, float] = {}
        self._seen_order: deque[str] = deque(maxlen=max(1, int(seen_capacity)))
        self._seen: set[str] = set()
        self._accepted = 0
        self._rejected = 0
        self._config_error: str | None = None
        self._state_error: str | None = None
        try:
            self.config = load_frozen_evidence(self.config_path)
        except FrozenLeadLagEvidenceError as exc:
            self.config = None
            self._config_error = exc.code
        self._restore_seen_events()
        self._restore_state()
        self._write_status(
            code="READY" if self.config is not None else self._config_error or "CONFIG_UNAVAILABLE"
        )

    @property
    def enabled(self) -> bool:
        return self.config is not None

    @property
    def real_execution(self) -> bool:
        return False

    def on_trade(
        self,
        trade_event: Mapping[str, Any],
        hl_quote: Mapping[str, Any] | None,
        *,
        now_ms: int,
    ) -> LeadLagEventOutcome:
        event_id = str(trade_event.get("event_id") or "")
        coin = str(trade_event.get("coin") or "").upper()
        if not event_id or not coin:
            return LeadLagEventOutcome(event_id, coin, "INVALID_TRADE_EVENT")
        if event_id in self._seen:
            return LeadLagEventOutcome(event_id, coin, "DUPLICATE_EVENT")
        self._remember(event_id)

        trade_price = _finite_positive(trade_event.get("px"))
        received_ms = _positive_int(
            trade_event.get("recv_wall_ts_ms") or trade_event.get("ts_wall_ms")
        )
        if trade_price is None or received_ms is None:
            return LeadLagEventOutcome(event_id, coin, "INVALID_TRADE_EVENT")

        previous_price = self._last_trade_price.get(coin)
        self._last_trade_price[coin] = trade_price
        self._persist_state()
        if self.config is None:
            return LeadLagEventOutcome(
                event_id,
                coin,
                self._config_error or "EVIDENCE_NOT_AVAILABLE",
            )
        if coin not in set(self.config["coins"]):
            return LeadLagEventOutcome(event_id, coin, "COIN_OUTSIDE_FROZEN_SCOPE")
        if previous_price is None:
            outcome = LeadLagEventOutcome(event_id, coin, "BASELINE_INITIALIZED")
            self._write_status(code=outcome.code, outcome=outcome)
            return outcome

        shock_bps = (trade_price / previous_price - 1.0) * 10_000.0
        threshold_bps = float(self.config.get("seuil_choc_bps") or 0.0)
        if abs(shock_bps) < threshold_bps:
            return LeadLagEventOutcome(event_id, coin, "BELOW_FROZEN_SHOCK_THRESHOLD")

        latency_ms = float(int(now_ms) - received_ms)
        if latency_ms < 0:
            return self._reject(
                event_id,
                coin,
                "NON_CAUSAL_RUNTIME_CLOCK",
                latency_ms=latency_ms,
                shock_bps=shock_bps,
            )
        latency_budget = self.config["latency_budget"]
        half_life_ms = float(latency_budget["alpha_half_life_p95_ms"])
        safety_margin_ms = float(latency_budget["safety_margin_ms"])
        if latency_ms + safety_margin_ms >= half_life_ms:
            return self._reject(
                event_id,
                coin,
                "ALPHA_HALF_LIFE_EXPIRED",
                latency_ms=latency_ms,
                shock_bps=shock_bps,
            )

        truth, truth_error = _execution_truth(
            coin=coin,
            event_id=event_id,
            quote=hl_quote,
            trade_received_ms=received_ms,
            max_age_ms=min(
                half_life_ms - safety_margin_ms,
                float(self.paper_engine.config.max_execution_book_age_ms),
            ),
        )
        if truth is None:
            return self._reject(
                event_id,
                coin,
                truth_error or "NO_LIVE_EXECUTABLE_BOOK",
                latency_ms=latency_ms,
                shock_bps=shock_bps,
            )

        earliest_horizon = min(self.config["observable_horizons_ms"])
        base_edge_bps = float(self.config["edge_net_par_horizon_bps"][earliest_horizon])
        edge_remaining_bps = base_edge_bps * math.pow(0.5, latency_ms / half_life_ms)
        action = LifecycleAction.OPEN_LONG if shock_bps > 0 else LifecycleAction.OPEN_SHORT
        signed_size = 1.0 if action == LifecycleAction.OPEN_LONG else -1.0
        delta = LeaderDelta(
            delta_id=f"lead-lag:{event_id}",
            wallet="lead_lag_binance_shadow",
            coin=coin,
            action=action,
            previous_size=0.0,
            current_size=signed_size,
            delta_size=signed_size,
            observed_at_ms=int(now_ms),
            leader_event_time_ms=received_ms,
            source="lead_lag_event_runtime",
            confidence=1.0,
            evidence_ref=str(self.config_path),
            leader_reference_price=trade_price,
        )
        total_cost_bps = float(self.config["costs"]["round_trip_bps"])
        result = self.paper_engine.apply_delta(
            delta,
            market_price=truth.mid_price,
            observed_at_ms=int(now_ms),
            edge_remaining_bps=edge_remaining_bps,
            spread_bps=truth.spread_bps,
            estimated_slippage_bps=max(0.0, total_cost_bps - truth.spread_bps),
            top_depth_usdt=truth.visible_notional(
                "BUY" if action == LifecycleAction.OPEN_LONG else "SELL"
            ),
            wallet_score=100.0,
            signal_score=100.0,
            marks={coin: truth.mid_price},
            execution_truth=truth,
            decision_context={
                "event_driven": True,
                "source_event_id": event_id,
                "shock_bps": shock_bps,
                "runtime_latency_ms": latency_ms,
                "alpha_half_life_p95_ms": half_life_ms,
                "real_execution": False,
            },
        )
        code = "PAPER_ACCEPTED" if result.accepted else _paper_refusal_code(result)
        outcome = LeadLagEventOutcome(
            event_id=event_id,
            coin=coin,
            code=code,
            accepted=result.accepted,
            latency_ms=latency_ms,
            edge_remaining_bps=edge_remaining_bps,
            paper_result=result,
        )
        self._record(
            outcome,
            shock_bps=shock_bps,
            snapshot_id=truth.snapshot_id,
            reason_codes=result.reason_codes,
            ledger_snapshot=result.ledger_snapshot,
        )
        if result.accepted:
            self._accepted += 1
        else:
            self._rejected += 1
        self._persist_state()
        self._write_status(code=code, outcome=outcome)
        return outcome

    def _reject(
        self,
        event_id: str,
        coin: str,
        code: str,
        *,
        latency_ms: float,
        shock_bps: float,
    ) -> LeadLagEventOutcome:
        outcome = LeadLagEventOutcome(event_id, coin, code, latency_ms=latency_ms)
        self._rejected += 1
        self._record(outcome, shock_bps=shock_bps)
        self._persist_state()
        self._write_status(code=code, outcome=outcome)
        return outcome

    def _record(self, outcome: LeadLagEventOutcome, **extra: Any) -> None:
        self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "event_id": outcome.event_id,
            "coin": outcome.coin,
            "code": outcome.code,
            "accepted": outcome.accepted,
            "latency_ms": outcome.latency_ms,
            "edge_remaining_bps": outcome.edge_remaining_bps,
            "real_execution": False,
            **extra,
        }
        with self.decisions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _state_payload(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "real_execution": False,
            "accepted": self._accepted,
            "rejected": self._rejected,
            "last_trade_price": dict(self._last_trade_price),
            "positions": [asdict(position) for position in self.paper_engine.positions],
        }

    def _persist_state(self) -> None:
        """Atomic snapshot; failure is visible in status but never kills collection."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(self._state_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.state_path)
            self._state_error = None
        except OSError as exc:
            self._state_error = f"STATE_WRITE_FAILED:{exc.__class__.__name__}"
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _restore_state(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, TypeError, ValueError) as exc:
            self._state_error = f"STATE_READ_FAILED:{exc.__class__.__name__}"
            return
        if not isinstance(payload, dict) or payload.get("schema") != STATE_SCHEMA:
            self._state_error = "STATE_SCHEMA_INVALID"
            return
        if payload.get("real_execution") is not False:
            self._state_error = "STATE_SAFETY_INVALID"
            return
        restored_prices: dict[str, float] = {}
        for coin, value in dict(payload.get("last_trade_price") or {}).items():
            parsed = _finite_positive(value)
            if parsed is not None:
                restored_prices[str(coin).upper()] = parsed
        self._last_trade_price = restored_prices
        try:
            self._accepted = max(0, int(payload.get("accepted") or 0))
            self._rejected = max(0, int(payload.get("rejected") or 0))
        except (TypeError, ValueError):
            self._accepted = self._rejected = 0
        for raw in payload.get("positions") or []:
            if not isinstance(raw, dict):
                continue
            try:
                position = PaperPosition(
                    position_id=str(raw["position_id"]),
                    coin=str(raw["coin"]),
                    side=str(raw["side"]),
                    quantity=float(raw["quantity"]),
                    entry_price=float(raw["entry_price"]),
                    notional_usdt=float(raw["notional_usdt"]),
                    opened_at_ms=int(raw["opened_at_ms"]),
                    source_delta_id=str(raw["source_delta_id"]),
                    leader_wallet=str(raw["leader_wallet"]),
                    margin_locked_usdt=float(raw.get("margin_locked_usdt") or 0.0),
                    leverage_effective=float(raw.get("leverage_effective") or 1.0),
                    leg_notional_usdt=tuple(float(v) for v in (raw.get("leg_notional_usdt") or ())),
                )
                self.paper_engine.restore_position(
                    position,
                    refs={"runtime": "lead_lag_event", "state_path": str(self.state_path)},
                )
            except (KeyError, TypeError, ValueError):
                self._state_error = "STATE_POSITION_INVALID"
                continue

    def _write_status(
        self,
        *,
        code: str,
        outcome: LeadLagEventOutcome | None = None,
    ) -> None:
        payload = {
            "enabled": self.enabled,
            "real_execution": False,
            "code": code,
            "config_path": str(self.config_path),
            "state_path": str(self.state_path),
            "state_error": self._state_error,
            "accepted": self._accepted,
            "rejected": self._rejected,
            "open_paper_positions": len(self.paper_engine.positions),
            "last_event_id": outcome.event_id if outcome else None,
            "last_coin": outcome.coin if outcome else None,
            "last_latency_ms": outcome.latency_ms if outcome else None,
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.status_path)
        except OSError:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _remember(self, event_id: str) -> None:
        if len(self._seen_order) == self._seen_order.maxlen and self._seen_order:
            self._seen.discard(self._seen_order[0])
        self._seen_order.append(event_id)
        self._seen.add(event_id)

    def _restore_seen_events(self) -> None:
        try:
            with self.decisions_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 1_000_000))
                rows = handle.read().decode("utf-8", errors="ignore").splitlines()
        except OSError:
            return
        for row in rows:
            try:
                event_id = str(json.loads(row).get("event_id") or "")
            except (TypeError, ValueError):
                continue
            if event_id:
                self._remember(event_id)


def _execution_truth(
    *,
    coin: str,
    event_id: str,
    quote: Mapping[str, Any] | None,
    trade_received_ms: int,
    max_age_ms: float,
) -> tuple[ExecutionTruth | None, str | None]:
    if not isinstance(quote, Mapping):
        return None, "NO_LIVE_EXECUTABLE_BOOK"
    quote_received_ms = _positive_int(quote.get("recv_wall_ts_ms"))
    if quote_received_ms is None:
        return None, "BOOK_TIMESTAMP_MISSING"
    if quote_received_ms > trade_received_ms:
        return None, "NON_CAUSAL_BOOK_AFTER_TRIGGER"
    if trade_received_ms - quote_received_ms > max(0.0, max_age_ms):
        return None, "EXECUTION_BOOK_STALE_FOR_ALPHA"
    try:
        return (
            ExecutionTruth.from_levels(
                coin=coin,
                bids=[(quote.get("bid"), quote.get("bid_sz"))],
                asks=[(quote.get("ask"), quote.get("ask_sz"))],
                received_ts_ms=quote_received_ms,
                exchange_ts_ms=_positive_int(quote.get("ts_ex")),
                source="hyperliquid_ws_bbo_read_only",
                snapshot_id=f"lead-lag-book:{event_id}",
            ),
            None,
        )
    except (TypeError, ValueError):
        return None, "EXECUTION_BOOK_INVALID"


def _paper_refusal_code(result: PaperDecisionResult) -> str:
    if result.reason_codes:
        return str(result.reason_codes[0])
    return "PAPER_ENGINE_REJECTED"


def _finite_positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


__all__ = ["LeadLagEventOutcome", "LeadLagEventPaperRuntime"]
