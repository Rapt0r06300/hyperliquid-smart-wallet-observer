"""Resumable Stage Machine for the ANALYZE phase in Alina SmartFlow."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
import hashlib
from typing import Any, Mapping

from hl_observer.control_plane.phase_state import sha256_json, parse_iso_utc, _now

ANALYZE_STAGES = (
    "DRAIN",
    "QUALITY",
    "REPLAY",
    "BACKTEST",
    "OOS",
    "FORWARD_PAPER",
    "PNL_PROOF",
    "SCOREBOARD",
    "DONE",
)

STAGE_TRANSITIONS: dict[str, str] = {
    "DRAIN": "QUALITY",
    "QUALITY": "REPLAY",
    "REPLAY": "BACKTEST",
    "BACKTEST": "OOS",
    "OOS": "FORWARD_PAPER",
    "FORWARD_PAPER": "PNL_PROOF",
    "PNL_PROOF": "SCOREBOARD",
    "SCOREBOARD": "DONE",
}


@dataclass
class StageReceipt:
    stage: str
    status: str  # "PENDING", "RUNNING", "COMPLETE", "FAILED"
    code_sha: str
    config_hash: str
    dataset_selection_id: str
    started_at_utc: str
    completed_at_utc: str | None = None
    output_artifact_hashes: dict[str, str] = field(default_factory=dict)
    failure_reason: str | None = None
    checkpoint_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_digest(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> StageReceipt:
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown StageReceipt fields: {sorted(unknown)}")
        obj = cls(**dict(raw))
        validate_stage_receipt(obj)
        return obj


def validate_stage_receipt(r: StageReceipt) -> None:
    if r.stage not in ANALYZE_STAGES:
        raise ValueError(f"Invalid analyze stage: {r.stage}")
    if r.status not in ("PENDING", "RUNNING", "COMPLETE", "FAILED"):
        raise ValueError(f"Invalid stage status: {r.status}")
    if not r.code_sha or not r.config_hash or not r.dataset_selection_id:
        raise ValueError("StageReceipt missing required identity hashes")
    parse_iso_utc(r.started_at_utc)
    if r.completed_at_utc:
        parse_iso_utc(r.completed_at_utc)


class AnalyzeStageMachine:
    """Manages the sequential execution and state receipts of the ANALYZE phase stages."""

    def __init__(
        self,
        source_collection_epoch: int,
        dataset_selection_id: str,
        code_sha: str,
        config_hash: str,
        completed_stage_receipts: list[StageReceipt] | None = None,
    ):
        if not isinstance(source_collection_epoch, int) or source_collection_epoch < 1:
            raise ValueError("source_collection_epoch must be a positive integer")
        if not dataset_selection_id or not code_sha or not config_hash:
            raise ValueError("Missing required hashes for AnalyzeStageMachine")

        self.source_collection_epoch = source_collection_epoch
        self.dataset_selection_id = dataset_selection_id
        self.code_sha = code_sha
        self.config_hash = config_hash
        self.receipts: list[StageReceipt] = completed_stage_receipts or []

        # Validate provided receipts continuity
        self._validate_receipts_lineage()

    def _validate_receipts_lineage(self) -> None:
        for idx, r in enumerate(self.receipts):
            validate_stage_receipt(r)
            if r.stage != ANALYZE_STAGES[idx]:
                raise ValueError(f"Stage receipt out of sequence: expected {ANALYZE_STAGES[idx]}, got {r.stage}")
            if r.status != "COMPLETE":
                raise ValueError(f"Historical stage receipt must be COMPLETE, got {r.status} for {r.stage}")

    @property
    def current_stage(self) -> str:
        if not self.receipts:
            return "DRAIN"
        last = self.receipts[-1]
        if last.stage == "DONE":
            return "DONE"
        return STAGE_TRANSITIONS[last.stage]

    def record_stage_completion(
        self,
        stage: str,
        output_artifact_hashes: dict[str, str],
        started_at_utc: str,
        completed_at_utc: str | None = None,
        checkpoint_id: str | None = None,
    ) -> StageReceipt:
        expected = self.current_stage
        if stage != expected:
            raise ValueError(f"Cannot complete stage '{stage}'; expected next stage is '{expected}'")

        now = completed_at_utc or _now()
        receipt = StageReceipt(
            stage=stage,
            status="COMPLETE",
            code_sha=self.code_sha,
            config_hash=self.config_hash,
            dataset_selection_id=self.dataset_selection_id,
            started_at_utc=started_at_utc,
            completed_at_utc=now,
            output_artifact_hashes=output_artifact_hashes,
            checkpoint_id=checkpoint_id,
        )
        validate_stage_receipt(receipt)
        self.receipts.append(receipt)
        return receipt

    def record_stage_failure(
        self,
        stage: str,
        failure_reason: str,
        started_at_utc: str,
        completed_at_utc: str | None = None,
    ) -> StageReceipt:
        expected = self.current_stage
        if stage != expected:
            raise ValueError(f"Cannot record failure for stage '{stage}'; expected current stage is '{expected}'")

        now = completed_at_utc or _now()
        receipt = StageReceipt(
            stage=stage,
            status="FAILED",
            code_sha=self.code_sha,
            config_hash=self.config_hash,
            dataset_selection_id=self.dataset_selection_id,
            started_at_utc=started_at_utc,
            completed_at_utc=now,
            failure_reason=failure_reason,
        )
        validate_stage_receipt(receipt)
        return receipt
