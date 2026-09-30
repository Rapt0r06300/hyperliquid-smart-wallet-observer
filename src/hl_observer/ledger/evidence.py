from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from hl_observer.features import MarketFeatureVector
from hl_observer.hyperliquid.schemas import PaperOrder, RiskDecision, SignalCandidate


EVIDENCE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "decision_id",
    "decision_type",
    "source_wallet",
    "coin",
    "side",
    "signal_type",
    "feature_hash",
    "market_quality_mode",
    "market_quality_reasons",
    "edge_remaining_bps",
    "spread_bps",
    "liquidity_score",
    "risk_allowed",
    "risk_decision",
    "risk_reasons",
    "paper_order_id",
    "paper_notional_usdc",
    "paper_fill_price",
    "paper_rejected_reason",
    "source_refs",
    "created_at_ms",
    "evidence_hash",
)


@dataclass(frozen=True, slots=True)
class EvidenceChainEntry:
    run_id: str
    decision_id: str
    decision_type: str
    source_wallet: str
    coin: str
    side: str
    signal_type: str
    feature_hash: str | None
    market_quality_mode: str
    market_quality_reasons: tuple[str, ...]
    edge_remaining_bps: float
    spread_bps: float | None
    liquidity_score: float | None
    risk_allowed: bool
    risk_decision: str
    risk_reasons: tuple[str, ...]
    paper_order_id: str | None
    paper_notional_usdc: float | None
    paper_fill_price: float | None
    paper_rejected_reason: str | None
    source_refs: tuple[str, ...]
    created_at_ms: int
    evidence_hash: str = ""

    def with_hash(self) -> "EvidenceChainEntry":
        payload = {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "decision_type": self.decision_type,
            "source_wallet": self.source_wallet,
            "coin": self.coin,
            "side": self.side,
            "signal_type": self.signal_type,
            "feature_hash": self.feature_hash,
            "market_quality_mode": self.market_quality_mode,
            "market_quality_reasons": self.market_quality_reasons,
            "edge_remaining_bps": self.edge_remaining_bps,
            "spread_bps": self.spread_bps,
            "liquidity_score": self.liquidity_score,
            "risk_allowed": self.risk_allowed,
            "risk_decision": self.risk_decision,
            "risk_reasons": self.risk_reasons,
            "paper_order_id": self.paper_order_id,
            "paper_notional_usdc": self.paper_notional_usdc,
            "paper_fill_price": self.paper_fill_price,
            "paper_rejected_reason": self.paper_rejected_reason,
            "source_refs": self.source_refs,
            "created_at_ms": self.created_at_ms,
        }
        digest = "ev:" + sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:32]
        return EvidenceChainEntry(**{**asdict(self), "evidence_hash": digest})

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["market_quality_reasons"] = "|".join(self.market_quality_reasons)
        row["risk_reasons"] = "|".join(self.risk_reasons)
        row["source_refs"] = "|".join(self.source_refs)
        return row


def build_evidence_entry(
    *,
    run_id: str,
    signal: SignalCandidate,
    market: MarketFeatureVector | None,
    risk_decision: RiskDecision,
    paper_order: PaperOrder | None = None,
    source_refs: tuple[str, ...] = ("allMids", "l2Book"),
) -> EvidenceChainEntry:
    decision_value = getattr(risk_decision.decision, "value", str(risk_decision.decision))
    paper_value = getattr(paper_order.decision, "value", str(paper_order.decision)) if paper_order else None
    if paper_order and paper_order.notional_usdc > 0:
        decision_type = "PAPER_SIMULATED"
    elif risk_decision.allowed:
        decision_type = "PAPER_ALLOWED_NO_ORDER_RECORDED"
    else:
        decision_type = "NO_TRADE"
    if paper_value and paper_order and paper_order.rejected_reason:
        decision_type = paper_value
    entry = EvidenceChainEntry(
        run_id=run_id,
        decision_id=signal.id,
        decision_type=decision_type,
        source_wallet=signal.source_wallet,
        coin=signal.coin,
        side=signal.side,
        signal_type=signal.signal_type,
        feature_hash=market.feature_hash if market else None,
        market_quality_mode=market.quality_mode if market else "NO_TRADE",
        market_quality_reasons=market.quality_reasons if market else ("MARKET_FEATURES_MISSING",),
        edge_remaining_bps=signal.edge_remaining_bps,
        spread_bps=market.spread_bps if market else signal.estimated_spread_bps,
        liquidity_score=market.liquidity_score if market else None,
        risk_allowed=risk_decision.allowed,
        risk_decision=decision_value,
        risk_reasons=tuple(risk_decision.reasons),
        paper_order_id=paper_order.order_id if paper_order else None,
        paper_notional_usdc=paper_order.notional_usdc if paper_order else None,
        paper_fill_price=paper_order.simulated_fill_price if paper_order else None,
        paper_rejected_reason=paper_order.rejected_reason if paper_order else None,
        source_refs=source_refs,
        created_at_ms=signal.timestamp_ms,
    )
    return entry.with_hash()


@dataclass(frozen=True, slots=True)
class EvidenceExportResult:
    json_path: Path
    csv_path: Path
    entries: int


def write_evidence_ledger(
    entries: list[EvidenceChainEntry],
    output_dir: Path | str,
    *,
    run_id: str,
) -> EvidenceExportResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    safe_run_id = _safe_run_id(run_id)
    json_path = output / f"evidence_chain_{safe_run_id}.json"
    csv_path = output / f"evidence_chain_{safe_run_id}.csv"
    rows = [entry.to_row() for entry in entries]
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVIDENCE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return EvidenceExportResult(json_path=json_path, csv_path=csv_path, entries=len(entries))


def load_evidence_ledger(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_evidence(entries: list[EvidenceChainEntry] | list[dict[str, Any]], decision_id: str) -> dict[str, Any] | None:
    for entry in entries:
        row = entry.to_row() if isinstance(entry, EvidenceChainEntry) else entry
        if row.get("decision_id") == decision_id:
            return row
    return None


def _safe_run_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return safe.strip("_") or "run"
