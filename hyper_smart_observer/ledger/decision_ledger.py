"""DecisionLedger evidence chain (Phase 3).

Every SignalCandidate / NoTradeDecision becomes a DecisionLedgerEntry that links
the decision to the EXACT market feature snapshot used (feature_hash) plus the
reason codes and the read-only source refs. Each entry carries a reproducible
SHA-256 `evidence_hash` so a decision can be reconstructed and verified.

SIMULATION ONLY. No orders, no execution, no fabricated data: when a feature is
missing the entry records feature_hash=None + an explicit reason.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

LEDGER_COLUMNS: tuple[str, ...] = (
    "run_id",
    "decision_id",
    "decision_type",
    "paper_intent_id",
    "paper_trade_id",
    "coin",
    "wallet",
    "reason_codes",
    "feature_hash",
    "edge_remaining_bps",
    "spread_bps",
    "liquidity_score",
    "copy_degradation_bps",
    "exit_trigger",
    "exit_reference_price",
    "realized_net_pnl",
    "source_health",
    "raw_refs",
    "created_at",
    "evidence_hash",
)


@dataclass(frozen=True)
class DecisionLedgerEntry:
    run_id: str
    decision_id: str
    decision_type: str  # ACCEPT_PAPER | REJECT_NO_TRADE | NO_TRADE
    paper_intent_id: str | None
    paper_trade_id: str | None
    coin: str
    wallet: str
    reason_codes: tuple[str, ...]
    feature_hash: str | None
    edge_remaining_bps: float | None
    spread_bps: float | None
    liquidity_score: float | None
    copy_degradation_bps: float | None
    source_health: str
    raw_refs: tuple[str, ...]
    created_at: str
    exit_trigger: str | None = None
    exit_reference_price: float | None = None
    realized_net_pnl: float | None = None
    evidence_hash: str = ""

    def with_hash(self) -> "DecisionLedgerEntry":
        payload = "|".join(
            [
                self.run_id,
                self.decision_id,
                self.decision_type,
                str(self.paper_intent_id),
                str(self.paper_trade_id),
                self.coin,
                self.wallet,
                ",".join(self.reason_codes),
                str(self.feature_hash),
                str(self.edge_remaining_bps),
                str(self.spread_bps),
                str(self.liquidity_score),
                str(self.copy_degradation_bps),
                str(self.exit_trigger),
                str(self.exit_reference_price),
                str(self.realized_net_pnl),
                self.source_health,
                ",".join(self.raw_refs),
            ]
        )
        digest = "ev:" + sha256(payload.encode("utf-8")).hexdigest()[:32]
        return DecisionLedgerEntry(**{**asdict(self), "reason_codes": self.reason_codes,
                                      "raw_refs": self.raw_refs, "evidence_hash": digest})

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["reason_codes"] = ",".join(self.reason_codes)
        row["raw_refs"] = ",".join(self.raw_refs)
        return row


def _feature_for(features_by_coin: dict[str, Any] | None, coin: str | None) -> Any:
    if not features_by_coin or not coin:
        return None
    return features_by_coin.get(coin.upper())


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default) if obj is not None else default


def _raw_refs(feature: Any) -> tuple[str, ...]:
    refs = ["allMids", "l2Book"]
    if _attr(feature, "volatility_context") is not None:
        refs.append("candleSnapshot")
    return tuple(refs)


def build_decision_ledger(
    signals: list[Any],
    no_trades: list[Any],
    features_by_coin: dict[str, Any] | None = None,
    *,
    run_id: str = "",
    paper_refs_by_decision_id: dict[str, dict[str, str | None]] | None = None,
) -> list[DecisionLedgerEntry]:
    """Build append-only evidence entries from a copy-run's decisions."""
    entries: list[DecisionLedgerEntry] = []
    paper_refs_by_decision_id = paper_refs_by_decision_id or {}

    for signal in signals or []:
        coin = str(_attr(signal, "coin", "")).upper()
        feature = _feature_for(features_by_coin, coin)
        feature_hash = _attr(feature, "feature_hash")
        decision = _attr(signal, "decision")
        decision_type = getattr(decision, "value", str(decision))
        paper_refs = paper_refs_by_decision_id.get(str(_attr(signal, "candidate_id", "")), {})
        entries.append(
            DecisionLedgerEntry(
                run_id=run_id,
                decision_id=str(_attr(signal, "candidate_id", "")),
                decision_type=decision_type,
                paper_intent_id=paper_refs.get("paper_intent_id"),
                paper_trade_id=paper_refs.get("paper_trade_id"),
                coin=coin,
                wallet=str(_attr(signal, "leader_wallet", "")),
                reason_codes=tuple(_attr(signal, "refusal_reasons", []) or []),
                feature_hash=feature_hash,
                edge_remaining_bps=_attr(signal, "edge_remaining_bps"),
                spread_bps=_attr(signal, "spread_bps"),
                liquidity_score=_attr(signal, "liquidity_score"),
                copy_degradation_bps=_attr(signal, "copy_degradation_bps"),
                source_health=str(_attr(feature, "source_health", "UNKNOWN")),
                raw_refs=_raw_refs(feature),
                created_at=str(_attr(signal, "observed_at", "")),
            ).with_hash()
        )

    for nt in no_trades or []:
        coin = _attr(nt, "coin")
        coin = str(coin).upper() if coin else "GLOBAL"
        feature = _feature_for(features_by_coin, coin) if coin != "GLOBAL" else None
        reason = _attr(nt, "reason")
        reason_code = getattr(reason, "value", str(reason))
        entries.append(
            DecisionLedgerEntry(
                run_id=run_id,
                decision_id=str(_attr(nt, "decision_id", "")),
                decision_type="NO_TRADE",
                paper_intent_id=None,
                paper_trade_id=None,
                coin=coin,
                wallet=str(_attr(nt, "leader_wallet", "") or ""),
                reason_codes=(reason_code,),
                feature_hash=_attr(feature, "feature_hash"),
                edge_remaining_bps=None,
                spread_bps=_attr(feature, "spread_bps"),
                liquidity_score=_attr(feature, "liquidity_score"),
                copy_degradation_bps=None,
                source_health=str(_attr(feature, "source_health", "UNKNOWN")),
                raw_refs=_raw_refs(feature),
                created_at=str(_attr(nt, "created_at", "")),
            ).with_hash()
        )
    return entries


@dataclass(frozen=True)
class DecisionLedgerExportResult:
    json_path: Path
    csv_path: Path
    entries: int


def write_decision_ledger(entries: list[DecisionLedgerEntry], output_dir: Path | str, *, run_id: str) -> DecisionLedgerExportResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_run = run_id.replace("/", "_").replace(":", "_") or "run"
    json_path = output_dir / f"decision_ledger_{safe_run}.json"
    csv_path = output_dir / f"decision_ledger_{safe_run}.csv"
    rows = [e.to_row() for e in entries]
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return DecisionLedgerExportResult(json_path, csv_path, len(rows))


def load_decision_ledger(json_path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(json_path).read_text(encoding="utf-8"))


def find_decision(entries: list[Any], decision_id: str) -> dict[str, Any] | None:
    for entry in entries:
        row = entry if isinstance(entry, dict) else entry.to_row()
        if row.get("decision_id") == decision_id:
            return row
    return None


def feature_hash_for_decision(entries: list[Any], decision_id: str) -> str | None:
    row = find_decision(entries, decision_id)
    return row.get("feature_hash") if row else None
