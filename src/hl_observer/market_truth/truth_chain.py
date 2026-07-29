"""Signal-to-ledger truth chain with append-only evidence."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping

from hl_observer.market_truth.executable_replay import (
    ExecutableFill,
    ReplayIntent,
    replay_executable_fill,
)
from hl_observer.simulation.paper_event import PaperEvent
from hl_observer.simulation.paper_ledger import PaperLedger


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    chain_id: str
    signal_id: str
    action: str
    coin: str
    position_side: str
    signal_observable_at_ms: int
    source_event_id: str | None
    source_tick_ref: str | None
    feed_quality_score: float | None
    fill: Mapping[str, Any]
    paper_event_ids: tuple[str, ...]
    reconciliation: Mapping[str, Any]
    outcome: str
    reason: str
    paper_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["fill"] = dict(self.fill)
        row["reconciliation"] = dict(self.reconciliation)
        row["paper_event_ids"] = list(self.paper_event_ids)
        return row


@dataclass(frozen=True, slots=True)
class TruthChainResult:
    fill: ExecutableFill
    paper_events: tuple[PaperEvent, ...]
    evidence: EvidenceRecord
    ledger_snapshot: Mapping[str, Any]

    @property
    def applied(self) -> bool:
        return self.evidence.outcome == "APPLIED"


class EvidenceWriter:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, evidence: EvidenceRecord) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    evidence.as_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())


class TruthChain:
    """Apply causal replay fills to the canonical PaperLedger."""

    def __init__(
        self,
        *,
        ledger: PaperLedger | None = None,
        evidence_path: Path | str | None = None,
    ) -> None:
        self.ledger = ledger or PaperLedger()
        self.evidence_writer = (
            EvidenceWriter(evidence_path) if evidence_path is not None else None
        )

    def execute(
        self,
        intent: ReplayIntent,
        canonical_events: Iterable[Mapping[str, Any] | Any],
    ) -> TruthChainResult:
        events = list(canonical_events)
        effective_intent, preparation_reason = self._prepare_intent(intent)
        before_count = len(self.ledger.events)
        if preparation_reason:
            paper_event = self.ledger.no_trade(
                coin=intent.coin,
                reason=preparation_reason,
                timestamp_ms=int(intent.signal_observable_at_ms),
                refs={"signal_id": intent.signal_id},
            )
            fill = replay_executable_fill(effective_intent, ())
            return self._result(
                intent=effective_intent,
                fill=fill,
                paper_events=(paper_event,),
                outcome="NO_TRADE",
                reason=preparation_reason,
            )

        fill = replay_executable_fill(effective_intent, events)
        if not fill.executable or fill.fill_price is None or fill.executed_at_ms is None:
            paper_event = self.ledger.no_trade(
                coin=intent.coin,
                reason=fill.reason,
                timestamp_ms=int(
                    fill.executed_at_ms
                    if fill.executed_at_ms is not None
                    else intent.signal_observable_at_ms
                ),
                refs=self._refs(intent, fill),
            )
            return self._result(
                intent=effective_intent,
                fill=fill,
                paper_events=(paper_event,),
                outcome="NO_TRADE",
                reason=fill.reason,
            )

        action = str(effective_intent.action).upper()
        if action in {"OPEN", "ADD", "INCREASE"}:
            self.ledger.open_position(
                coin=effective_intent.coin,
                side=effective_intent.position_side,
                notional_usdc=fill.filled_notional_usdc,
                fill_price=fill.fill_price,
                timestamp_ms=fill.executed_at_ms,
                fee_bps=fill.costs.fee_bps,
                refs=self._refs(effective_intent, fill),
            )
        else:
            self.ledger.reduce_or_close(
                coin=effective_intent.coin,
                side=effective_intent.position_side,
                quantity=fill.filled_quantity,
                fill_price=fill.fill_price,
                timestamp_ms=fill.executed_at_ms,
                fee_bps=fill.costs.fee_bps,
                reason="causal_%s" % action.lower(),
                refs=self._refs(effective_intent, fill),
            )
        if fill.book_mid is not None:
            self.ledger.mark_to_market(
                {str(effective_intent.coin).upper(): fill.book_mid},
                timestamp_ms=fill.executed_at_ms,
            )
        paper_events = tuple(self.ledger.events[before_count:])
        reconciliation = self.ledger.reconciliation()
        outcome = "APPLIED" if reconciliation.ok else "RECONCILIATION_FAILED"
        reason = fill.reason if reconciliation.ok else "PNL_RECONCILIATION_MISMATCH"
        return self._result(
            intent=effective_intent,
            fill=fill,
            paper_events=paper_events,
            outcome=outcome,
            reason=reason,
        )

    def reject(self, intent: ReplayIntent, *, reason: str) -> TruthChainResult:
        """Record an upstream refusal in the same ledger and evidence chain.

        Quality/canonicalization failures happen before executable replay. They
        must still be visible as NO_TRADE evidence rather than disappearing
        from the research dataset.
        """
        paper_event = self.ledger.no_trade(
            coin=intent.coin,
            reason=str(reason),
            timestamp_ms=int(intent.signal_observable_at_ms),
            refs={"signal_id": intent.signal_id, "stage": "UPSTREAM_QUALITY_GATE"},
        )
        fill = replace(
            replay_executable_fill(intent, ()),
            reason=str(reason),
        )
        return self._result(
            intent=intent,
            fill=fill,
            paper_events=(paper_event,),
            outcome="NO_TRADE",
            reason=str(reason),
        )

    def mark_from_events(
        self,
        canonical_events: Iterable[Mapping[str, Any] | Any],
        *,
        observable_at_ms: int,
    ) -> PaperEvent:
        marks: dict[str, float] = {}
        for event in canonical_events:
            row = event if isinstance(event, Mapping) else event.as_dict()
            if int(row.get("observable_at_ms") or 0) > int(observable_at_ms):
                continue
            coin = str(row.get("instrument") or "").upper()
            if not coin:
                continue
            mid = _mid_from_event(row)
            if mid is not None:
                marks[coin] = mid
        return self.ledger.mark_to_market(marks, timestamp_ms=int(observable_at_ms))

    def _prepare_intent(self, intent: ReplayIntent) -> tuple[ReplayIntent, str | None]:
        action = str(intent.action).upper()
        if action not in {"REDUCE", "CLOSE"}:
            return intent, None
        key = "%s:%s" % (
            str(intent.coin).upper(),
            str(intent.position_side).upper(),
        )
        position = self.ledger.positions.get(key)
        if position is None:
            return intent, "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
        if intent.requested_quantity is not None and intent.requested_quantity > 0:
            quantity = min(float(intent.requested_quantity), position.quantity)
        elif action == "CLOSE":
            quantity = position.quantity
        else:
            return intent, "REDUCE_QUANTITY_REQUIRED"
        return replace(
            intent,
            requested_quantity=quantity,
            requested_notional_usdc=None,
        ), None

    def _result(
        self,
        *,
        intent: ReplayIntent,
        fill: ExecutableFill,
        paper_events: tuple[PaperEvent, ...],
        outcome: str,
        reason: str,
    ) -> TruthChainResult:
        reconciliation = asdict(self.ledger.reconciliation())
        material = "|".join(
            (
                intent.signal_id,
                fill.source_event_id or "",
                ",".join(event.event_id for event in paper_events),
                outcome,
            )
        )
        evidence = EvidenceRecord(
            chain_id="truth:" + sha256(material.encode("utf-8")).hexdigest(),
            signal_id=intent.signal_id,
            action=str(intent.action).upper(),
            coin=str(intent.coin).upper(),
            position_side=str(intent.position_side).upper(),
            signal_observable_at_ms=int(intent.signal_observable_at_ms),
            source_event_id=fill.source_event_id,
            source_tick_ref=fill.source_tick_ref,
            feed_quality_score=fill.feed_quality_score,
            fill=fill.as_dict(),
            paper_event_ids=tuple(event.event_id for event in paper_events),
            reconciliation=reconciliation,
            outcome=outcome,
            reason=reason,
        )
        if self.evidence_writer is not None:
            self.evidence_writer.append(evidence)
        return TruthChainResult(
            fill=fill,
            paper_events=paper_events,
            evidence=evidence,
            ledger_snapshot=self.ledger.snapshot(),
        )

    @staticmethod
    def _refs(intent: ReplayIntent, fill: ExecutableFill) -> dict[str, Any]:
        return {
            "signal_id": intent.signal_id,
            "source_event_id": fill.source_event_id,
            "source_tick_ref": fill.source_tick_ref,
            "feed_quality_score": fill.feed_quality_score,
            "fill_status": fill.status.value,
            "fill_ratio": fill.fill_ratio,
            "costs": fill.costs.as_dict(),
        }


def _mid_from_event(event: Mapping[str, Any]) -> float | None:
    summary = event.get("parsed_summary")
    if isinstance(summary, Mapping):
        try:
            bid = float(summary["best_bid"])
            ask = float(summary["best_ask"])
            if 0 < bid <= ask:
                return (bid + ask) / 2.0
        except (KeyError, TypeError, ValueError):
            pass
    payload = event.get("raw_payload")
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    levels = data.get("levels")
    try:
        bid = float(levels[0][0]["px"])
        ask = float(levels[1][0]["px"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return (bid + ask) / 2.0 if 0 < bid <= ask else None


__all__ = [
    "EvidenceRecord",
    "EvidenceWriter",
    "TruthChain",
    "TruthChainResult",
]
