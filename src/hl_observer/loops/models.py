from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.decision_engine.local_engine import LocalDecision
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation
from hl_observer.testnet.models import TestnetOrderResult, unix_ms


def stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class ResearchThesis:
    thesis_id: str
    status: str
    observed_at_ms: int
    source: str
    coins_seen: int
    l2_books_seen: int
    wallets_seen: int
    fills_seen: int
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_observation(cls, observation: MainnetObservation) -> "ResearchThesis":
        fills_seen = sum(len(fills) for fills in observation.wallet_fills.values())
        notes: list[str] = []
        next_actions: list[str] = []
        if not observation.all_mids:
            notes.append("Aucun prix allMids exploitable: boucle en observation uniquement.")
            next_actions.append("Relancer le read-only observer ou verifier la connectivite Hyperliquid.")
        if observation.errors:
            notes.append("Observation partielle: certaines sources ont echoue.")
            next_actions.append("Consulter source_health et le journal de collecte avant toute execution testnet.")
        if observation.all_mids and not observation.errors:
            notes.append("Observation read-only exploitable pour scoring local.")
        payload = {
            "source": observation.source,
            "observed_at_ms": observation.observed_at_ms,
            "coins": sorted(observation.all_mids.keys()),
            "wallets": sorted(observation.wallet_states.keys()),
            "errors": observation.errors,
        }
        status = "EMPTY" if not observation.all_mids else "PARTIAL" if observation.errors else "READY"
        return cls(
            thesis_id=f"thesis-{stable_hash(payload)}",
            status=status,
            observed_at_ms=observation.observed_at_ms,
            source=observation.source,
            coins_seen=len(observation.all_mids),
            l2_books_seen=len(observation.l2_books),
            wallets_seen=len(observation.wallet_states),
            fills_seen=fills_seen,
            errors=list(observation.errors),
            notes=notes,
            next_actions=next_actions,
        )


@dataclass(frozen=True, slots=True)
class ExecutionFeedback:
    candidate_id: str | None
    decision_action: str
    execution_status: str
    reasons: list[str] = field(default_factory=list)
    testnet_result: dict[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_decision(
        cls,
        decision: LocalDecision,
        *,
        result: TestnetOrderResult | None = None,
        status: str = "PREPARED_ONLY",
    ) -> "ExecutionFeedback":
        return cls(
            candidate_id=decision.candidate_id,
            decision_action=decision.action.value,
            execution_status=result.status.upper() if result else status,
            reasons=list(result.reasons if result else decision.reasons),
            testnet_result=result.to_dict() if result else None,
            evidence=decision.evidence,
        )


@dataclass(frozen=True, slots=True)
class LearningSummary:
    total_decisions: int
    prepared_requests: int
    accepted_testnet: int
    rejected: int
    no_trade: int
    recurring_reasons: dict[str, int]
    next_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_feedback(cls, feedback: list[ExecutionFeedback]) -> "LearningSummary":
        recurring: dict[str, int] = {}
        prepared = accepted = rejected = no_trade = 0
        for item in feedback:
            if item.decision_action == "NO_TRADE":
                no_trade += 1
            if item.execution_status == "PREPARED_ONLY":
                prepared += 1
            if item.execution_status == "ACCEPTED":
                accepted += 1
            if item.execution_status in {"REJECTED", "REJECT_TESTNET_GUARD"}:
                rejected += 1
            for reason in item.reasons:
                recurring[reason] = recurring.get(reason, 0) + 1
        next_actions: list[str] = []
        if no_trade:
            next_actions.append("Analyser les raisons NO_TRADE avant d'assouplir les seuils.")
        if prepared and accepted == 0:
            next_actions.append("Valider les flags testnet/fake adapter avant toute execution testnet controlee.")
        if accepted:
            next_actions.append("Comparer fills/positions/PNL testnet contre le journal de decision.")
        if not feedback:
            next_actions.append("Aucun candidat: fournir des SignalCandidate issus du scanner read-only.")
        return cls(
            total_decisions=len(feedback),
            prepared_requests=prepared,
            accepted_testnet=accepted,
            rejected=rejected,
            no_trade=no_trade,
            recurring_reasons=dict(sorted(recurring.items(), key=lambda kv: (-kv[1], kv[0]))),
            next_actions=next_actions,
        )


@dataclass(frozen=True, slots=True)
class LoopRunResult:
    run_id: str
    thesis: ResearchThesis
    decisions: list[dict[str, Any]]
    feedback: list[ExecutionFeedback]
    learning: LearningSummary
    memory_dir: Path
    created_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["memory_dir"] = str(self.memory_dir)
        return data
