from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
from pathlib import Path
from typing import Any


class AcquisitionStatus(StrEnum):
    QUEUED = "QUEUED"
    SELECTED = "SELECTED"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"


class DataQualityStatus(StrEnum):
    SIMULATION_READY = "SIMULATION_READY"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class FetchRequest:
    request_id: str
    provider_name: str
    endpoint: str
    request_type: str
    wallet_address: str | None = None
    coin: str | None = None
    weight: int = 1
    priority: float = 0.0
    network_required: bool = True
    created_at_ms: int = 0
    not_before_ms: int = 0
    ttl_ms: int = 60_000
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        payload = {
            "provider_name": self.provider_name,
            "endpoint": self.endpoint,
            "request_type": self.request_type,
            "wallet_address": (self.wallet_address or "").lower(),
            "coin": (self.coin or "").upper(),
            "metadata": self.metadata,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    reason: str
    requested_weight: int
    remaining_before: int
    remaining_after: int


@dataclass(slots=True)
class RequestBudgetManager:
    network_read_enabled: bool = False
    rest_weight_limit_per_minute: int = 1200
    rest_weight_remaining: int = 1200

    def reserve(self, request: FetchRequest) -> BudgetDecision:
        requested = max(0, int(request.weight))
        before = max(0, int(self.rest_weight_remaining))
        if request.network_required and not self.network_read_enabled:
            return BudgetDecision(False, "NETWORK_READ_DISABLED", requested, before, before)
        if requested > before:
            return BudgetDecision(False, "RATE_LIMIT_GUARD", requested, before, before)
        self.rest_weight_remaining = before - requested
        return BudgetDecision(True, "BUDGET_RESERVED", requested, before, self.rest_weight_remaining)


@dataclass(frozen=True, slots=True)
class QueueDecision:
    status: AcquisitionStatus
    reason: str
    request_id: str


@dataclass(frozen=True, slots=True)
class FetchBatch:
    selected: tuple[FetchRequest, ...]
    blocked: tuple[QueueDecision, ...]
    remaining_pending: int


@dataclass(slots=True)
class PersistentFetchQueue:
    pending: list[FetchRequest] = field(default_factory=list)
    completed_request_ids: set[str] = field(default_factory=set)
    failed_request_ids: set[str] = field(default_factory=set)
    dedupe_keys: set[str] = field(default_factory=set)

    def enqueue(self, request: FetchRequest) -> QueueDecision:
        if request.request_id in self.completed_request_ids or request.request_id in self.failed_request_ids:
            return QueueDecision(AcquisitionStatus.DUPLICATE, "REQUEST_ALREADY_TERMINAL", request.request_id)
        if request.dedupe_key in self.dedupe_keys:
            return QueueDecision(AcquisitionStatus.DUPLICATE, "DUPLICATE_REQUEST", request.request_id)
        self.pending.append(request)
        self.dedupe_keys.add(request.dedupe_key)
        return QueueDecision(AcquisitionStatus.QUEUED, "QUEUED", request.request_id)

    def due_batch(self, *, now_ms: int, max_items: int, budget: RequestBudgetManager) -> FetchBatch:
        selected: list[FetchRequest] = []
        blocked: list[QueueDecision] = []
        keep_pending: list[FetchRequest] = []
        due = sorted(self.pending, key=lambda item: (-item.priority, item.created_at_ms, item.request_id))
        for request in due:
            if len(selected) >= max(0, max_items):
                keep_pending.append(request)
                continue
            if request.not_before_ms and request.not_before_ms > now_ms:
                keep_pending.append(request)
                continue
            if request.created_at_ms and request.ttl_ms and now_ms - request.created_at_ms > request.ttl_ms:
                blocked.append(QueueDecision(AcquisitionStatus.BLOCKED, "REQUEST_TTL_EXPIRED", request.request_id))
                self.failed_request_ids.add(request.request_id)
                continue
            decision = budget.reserve(request)
            if not decision.allowed:
                blocked.append(QueueDecision(AcquisitionStatus.BLOCKED, decision.reason, request.request_id))
                keep_pending.append(request)
                continue
            selected.append(request)
        self.pending = keep_pending
        return FetchBatch(tuple(selected), tuple(blocked), len(self.pending))

    def mark_done(self, request_id: str) -> None:
        self.completed_request_ids.add(request_id)

    def mark_failed(self, request_id: str) -> None:
        self.failed_request_ids.add(request_id)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "pending": [asdict(item) for item in self.pending],
            "completed_request_ids": sorted(self.completed_request_ids),
            "failed_request_ids": sorted(self.failed_request_ids),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "PersistentFetchQueue":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        queue = cls(
            pending=[FetchRequest(**item) for item in payload.get("pending", [])],
            completed_request_ids=set(payload.get("completed_request_ids", [])),
            failed_request_ids=set(payload.get("failed_request_ids", [])),
        )
        queue.dedupe_keys = {item.dedupe_key for item in queue.pending}
        return queue


@dataclass(frozen=True, slots=True)
class FetchResult:
    request: FetchRequest
    success: bool
    payload: Any
    fetched_at_ms: int
    local_received_at_ms: int
    exchange_ts_ms: int | None = None
    source_confidence_score: float = 1.0
    transport_latency_ms: int | None = None
    error_message: str | None = None
    source_url: str | None = None

    @property
    def payload_hash(self) -> str:
        body = json.dumps(self.payload, sort_keys=True, default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DataQualityConfig:
    max_data_age_ms: int = 5_000
    max_transport_latency_ms: int = 2_000
    min_source_confidence_score: float = 0.70
    require_timestamp: bool = True
    require_non_empty_payload: bool = True
    allow_low_confidence_for_pnl: bool = False


@dataclass(frozen=True, slots=True)
class DataQualityAssessment:
    status: DataQualityStatus
    accepted_for_simulation: bool
    confidence_score: float
    reasons: tuple[str, ...]
    next_action: str
    evidence: dict[str, Any]


class DataQualityGate:
    def __init__(self, config: DataQualityConfig | None = None) -> None:
        self.config = config or DataQualityConfig()

    def assess(self, result: FetchResult, *, now_ms: int, proves_pnl: bool = False) -> DataQualityAssessment:
        reasons: list[str] = []
        payload_size = _payload_size(result.payload)
        if not result.success:
            reasons.append("API_RESPONSE_INVALID")
        if result.error_message:
            reasons.append("SOURCE_UNAVAILABLE")
        if self.config.require_non_empty_payload and payload_size == 0:
            reasons.append("SOURCE_PAYLOAD_EMPTY")
        if self.config.require_timestamp and result.exchange_ts_ms is None:
            reasons.append("DATA_TIMESTAMP_MISSING")
        data_age_ms = None if result.exchange_ts_ms is None else max(0, now_ms - result.exchange_ts_ms)
        if data_age_ms is not None and data_age_ms > self.config.max_data_age_ms:
            reasons.append("STALE_DATA")
        if result.transport_latency_ms is not None and result.transport_latency_ms > self.config.max_transport_latency_ms:
            reasons.append("LATENCY_TOO_HIGH")
        confidence = _clamp(float(result.source_confidence_score), 0.0, 1.0)
        if confidence < self.config.min_source_confidence_score:
            reasons.append("LOW_CONFIDENCE_SOURCE")
        if proves_pnl and confidence < self.config.min_source_confidence_score and not self.config.allow_low_confidence_for_pnl:
            reasons.append("LOW_CONFIDENCE_CANNOT_PROVE_PNL")
        deduped = tuple(sorted(set(reasons)))
        accepted = not deduped
        if accepted:
            status = DataQualityStatus.SIMULATION_READY
            next_action = "ALLOW_FOR_SIGNAL_AND_PAPER_SIMULATION"
        elif result.success and payload_size > 0:
            status = DataQualityStatus.OBSERVE_ONLY
            next_action = "STORE_PROVENANCE_AND_WAIT_FOR_STRONGER_CONFIRMATION"
        else:
            status = DataQualityStatus.REJECTED
            next_action = "DO_NOT_USE_FOR_PNL_OR_SIGNAL"
        return DataQualityAssessment(
            status=status,
            accepted_for_simulation=accepted,
            confidence_score=confidence,
            reasons=deduped,
            next_action=next_action,
            evidence={
                "provider_name": result.request.provider_name,
                "endpoint": result.request.endpoint,
                "request_type": result.request.request_type,
                "wallet_address": result.request.wallet_address,
                "coin": result.request.coin,
                "payload_size": payload_size,
                "payload_hash": result.payload_hash,
                "exchange_ts_ms": result.exchange_ts_ms,
                "local_received_at_ms": result.local_received_at_ms,
                "data_age_ms": data_age_ms,
                "transport_latency_ms": result.transport_latency_ms,
                "source_confidence_score": confidence,
                "source_url": result.source_url,
                "proves_pnl": proves_pnl,
            },
        )


class DataAcquisitionEngine:
    def __init__(
        self,
        *,
        budget: RequestBudgetManager | None = None,
        queue: PersistentFetchQueue | None = None,
        quality_gate: DataQualityGate | None = None,
    ) -> None:
        self.budget = budget or RequestBudgetManager()
        self.queue = queue or PersistentFetchQueue()
        self.quality_gate = quality_gate or DataQualityGate()

    def enqueue(self, request: FetchRequest) -> QueueDecision:
        return self.queue.enqueue(request)

    def next_batch(self, *, now_ms: int, max_items: int) -> FetchBatch:
        return self.queue.due_batch(now_ms=now_ms, max_items=max_items, budget=self.budget)

    def assess_result(self, result: FetchResult, *, now_ms: int, proves_pnl: bool = False) -> DataQualityAssessment:
        assessment = self.quality_gate.assess(result, now_ms=now_ms, proves_pnl=proves_pnl)
        if assessment.accepted_for_simulation:
            self.queue.mark_done(result.request.request_id)
        else:
            self.queue.mark_failed(result.request.request_id)
        return assessment


def format_data_quality_assessment(assessment: DataQualityAssessment) -> str:
    lines = [
        "data_quality_gate=read_only",
        f"status={assessment.status.value}",
        f"accepted_for_simulation={str(assessment.accepted_for_simulation).lower()}",
        f"confidence_score={assessment.confidence_score:.4f}",
        f"reasons={','.join(assessment.reasons) if assessment.reasons else 'OK'}",
        f"next_action={assessment.next_action}",
    ]
    for key in (
        "provider_name",
        "endpoint",
        "request_type",
        "wallet_address",
        "coin",
        "payload_size",
        "data_age_ms",
        "transport_latency_ms",
        "payload_hash",
    ):
        lines.append(f"{key}={assessment.evidence.get(key)}")
    lines.append("execution=forbidden")
    lines.append("profit_guarantee=false")
    return "\n".join(lines)


def _payload_size(payload: Any) -> int:
    if payload is None:
        return 0
    if isinstance(payload, (list, tuple, set, dict, str)):
        return len(payload)
    return 1


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
