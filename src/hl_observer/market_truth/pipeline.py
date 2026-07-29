"""One ordered entry point for the causal market-truth chain.

This module prevents callers from skipping canonicalization or the data
quality gate and jumping directly from a raw message to a paper fill.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from hl_observer.market_truth.executable_replay import ReplayIntent
from hl_observer.market_truth.truth_chain import TruthChain, TruthChainResult
from hl_observer.normalization.market_events import (
    CanonicalEventWriter,
    CanonicalMarketEvent,
    canonicalize_tick_record,
)


@dataclass(frozen=True, slots=True)
class MarketTruthPipelineResult:
    truth: TruthChainResult
    canonical_events: tuple[CanonicalMarketEvent, ...]
    rejected_tick_reasons: tuple[str, ...]
    input_tick_count: int
    canonical_event_count: int

    @property
    def applied(self) -> bool:
        return self.truth.applied

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tick_count": self.input_tick_count,
            "canonical_event_count": self.canonical_event_count,
            "rejected_tick_reasons": list(self.rejected_tick_reasons),
            "canonical_event_ids": [
                event.event_id for event in self.canonical_events
            ],
            "truth": {
                "fill": self.truth.fill.as_dict(),
                "evidence": self.truth.evidence.as_dict(),
                "ledger_snapshot": dict(self.truth.ledger_snapshot),
            },
            "paper_only": True,
            "real_execution": False,
        }


class MarketTruthPipeline:
    """Canonicalize durable ticks, replay execution, then reconcile PnL."""

    def __init__(
        self,
        *,
        truth_chain: TruthChain | None = None,
        canonical_writer: CanonicalEventWriter | None = None,
    ) -> None:
        self.truth_chain = truth_chain or TruthChain()
        self.canonical_writer = canonical_writer

    def run(
        self,
        *,
        intent: ReplayIntent,
        durable_tick_records: Iterable[Mapping[str, Any]],
    ) -> MarketTruthPipelineResult:
        records = list(durable_tick_records)
        accepted: list[CanonicalMarketEvent] = []
        rejected_reasons: list[str] = []
        for record in records:
            result = canonicalize_tick_record(record)
            if result.event is not None:
                accepted.append(result.event)
            else:
                rejected_reasons.extend(result.reasons)

        accepted.sort(
            key=lambda event: (
                event.observable_at_ms,
                event.received_ts_ms,
                event.event_id,
            )
        )
        if self.canonical_writer is not None:
            self.canonical_writer.append(accepted)

        if not accepted:
            reason = _upstream_reason(rejected_reasons)
            truth = self.truth_chain.reject(intent, reason=reason)
        else:
            truth = self.truth_chain.execute(intent, accepted)
        return MarketTruthPipelineResult(
            truth=truth,
            canonical_events=tuple(accepted),
            rejected_tick_reasons=tuple(dict.fromkeys(rejected_reasons)),
            input_tick_count=len(records),
            canonical_event_count=len(accepted),
        )


def _upstream_reason(reasons: list[str]) -> str:
    if "DATA_QUALITY_GATE_NOT_READY" in reasons:
        return "DATA_QUALITY_GATE_NOT_READY"
    if "RAW_HASH_MISMATCH" in reasons:
        return "RAW_TICK_INTEGRITY_FAILED"
    if reasons:
        return "CANONICALIZATION_REJECTED:" + "|".join(dict.fromkeys(reasons))
    return "NO_DURABLE_MARKET_TICKS"


__all__ = [
    "MarketTruthPipeline",
    "MarketTruthPipelineResult",
]
