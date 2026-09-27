"""Atomic, fail-closed Phase Controller for Alina SmartFlow."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.control_plane.phase_state import (
    AlinaPhaseState,
    validate_phase_state,
    _now,
    sha256_json,
)


@dataclass(frozen=True)
class TransitionReceipt:
    request_id: str
    previous_epoch: int
    new_epoch: int
    previous_phase: str
    new_phase: str
    transitioned_at_utc: str
    state_digest: str
    state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PhaseController:
    """Manages atomic, fail-closed transitions for AlinaPhaseState."""

    def __init__(self, state_file_path: Path | str | None = None, initial_state: AlinaPhaseState | None = None):
        self.state_file_path = Path(state_file_path) if state_file_path else None
        if initial_state:
            validate_phase_state(initial_state)
            self._state = initial_state
        elif self.state_file_path and self.state_file_path.exists():
            self._state = self._load_from_disk()
        else:
            self._state = AlinaPhaseState()
            if self.state_file_path:
                self._save_to_disk()

    @property
    def current_state(self) -> AlinaPhaseState:
        return self._state

    def _load_from_disk(self) -> AlinaPhaseState:
        if not self.state_file_path or not self.state_file_path.exists():
            raise FileNotFoundError("Phase state file does not exist")
        with open(self.state_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AlinaPhaseState.from_dict(data)

    def _save_to_disk(self) -> None:
        if not self.state_file_path:
            return
        self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, indent=2, sort_keys=True)
        temp_path.replace(self.state_file_path)

    def transition_to_collect(
        self,
        *,
        request_id: str,
        requested_by: str = "operator",
        now_utc: str | None = None,
    ) -> TransitionReceipt:
        now = now_utc or _now()

        # Idempotency check
        if self._state.request_id == request_id and self._state.phase == "COLLECT":
            return TransitionReceipt(
                request_id=request_id,
                previous_epoch=self._state.epoch,
                new_epoch=self._state.epoch,
                previous_phase="COLLECT",
                new_phase="COLLECT",
                transitioned_at_utc=self._state.requested_at_utc,
                state_digest=self._state.content_digest(),
                state=self._state.to_dict(),
            )

        if self._state.phase not in ("IDLE", "COLLECT"):
            raise ValueError(f"Cannot transition to COLLECT from phase {self._state.phase}")

        prev_epoch = self._state.epoch
        prev_phase = self._state.phase
        new_epoch = prev_epoch + 1 if prev_phase != "COLLECT" else prev_epoch

        new_state = AlinaPhaseState(
            schema_version=1,
            phase="COLLECT",
            epoch=new_epoch,
            requested_at_utc=now,
            collection_started_at_utc=now,
            collection_cutoff_at_utc=None,
            source_collection_epoch=None,
            analysis_stage=None,
            requested_by=requested_by,
            request_id=request_id,
        )

        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()

        return TransitionReceipt(
            request_id=request_id,
            previous_epoch=prev_epoch,
            new_epoch=new_epoch,
            previous_phase=prev_phase,
            new_phase="COLLECT",
            transitioned_at_utc=now,
            state_digest=new_state.content_digest(),
            state=new_state.to_dict(),
        )

    def transition_to_analyze(
        self,
        *,
        request_id: str,
        requested_by: str = "operator",
        initial_stage: str = "DRAIN",
        now_utc: str | None = None,
    ) -> TransitionReceipt:
        now = now_utc or _now()

        # Idempotency check
        if self._state.request_id == request_id and self._state.phase == "ANALYZE":
            return TransitionReceipt(
                request_id=request_id,
                previous_epoch=self._state.epoch,
                new_epoch=self._state.epoch,
                previous_phase="ANALYZE",
                new_phase="ANALYZE",
                transitioned_at_utc=self._state.requested_at_utc,
                state_digest=self._state.content_digest(),
                state=self._state.to_dict(),
            )

        if self._state.phase != "COLLECT":
            raise ValueError(f"Transition to ANALYZE requires phase COLLECT, current: {self._state.phase}")
        if initial_stage != "DRAIN":
            raise ValueError("ANALYZE must begin at DRAIN")

        prev_epoch = self._state.epoch
        finished_collection_epoch = prev_epoch
        new_epoch = prev_epoch + 1

        new_state = AlinaPhaseState(
            schema_version=1,
            phase="ANALYZE",
            epoch=new_epoch,
            requested_at_utc=now,
            collection_started_at_utc=self._state.collection_started_at_utc,
            collection_cutoff_at_utc=now,
            source_collection_epoch=finished_collection_epoch,
            analysis_stage=initial_stage,
            requested_by=requested_by,
            request_id=request_id,
        )

        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()

        return TransitionReceipt(
            request_id=request_id,
            previous_epoch=prev_epoch,
            new_epoch=new_epoch,
            previous_phase="COLLECT",
            new_phase="ANALYZE",
            transitioned_at_utc=now,
            state_digest=new_state.content_digest(),
            state=new_state.to_dict(),
        )

    def transition_to_idle(
        self,
        *,
        request_id: str,
        requested_by: str = "operator",
        now_utc: str | None = None,
    ) -> TransitionReceipt:
        now = now_utc or _now()

        if self._state.request_id == request_id and self._state.phase == "IDLE":
            return TransitionReceipt(
                request_id=request_id,
                previous_epoch=self._state.epoch,
                new_epoch=self._state.epoch,
                previous_phase="IDLE",
                new_phase="IDLE",
                transitioned_at_utc=self._state.requested_at_utc,
                state_digest=self._state.content_digest(),
                state=self._state.to_dict(),
            )

        prev_epoch = self._state.epoch
        prev_phase = self._state.phase
        new_epoch = prev_epoch + 1 if prev_phase != "IDLE" else prev_epoch

        new_state = AlinaPhaseState(
            schema_version=1,
            phase="IDLE",
            epoch=new_epoch,
            requested_at_utc=now,
            collection_started_at_utc=None,
            collection_cutoff_at_utc=None,
            source_collection_epoch=None,
            analysis_stage=None,
            requested_by=requested_by,
            request_id=request_id,
        )

        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()

        return TransitionReceipt(
            request_id=request_id,
            previous_epoch=prev_epoch,
            new_epoch=new_epoch,
            previous_phase=prev_phase,
            new_phase="IDLE",
            transitioned_at_utc=now,
            state_digest=new_state.content_digest(),
            state=new_state.to_dict(),
        )

    def advance_analysis_stage(self, stage: str) -> AlinaPhaseState:
        if self._state.phase != "ANALYZE":
            raise ValueError(f"Cannot advance analysis_stage when phase is {self._state.phase}")
        ordered = ("DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE")
        if stage not in ordered:
            raise ValueError(f"Unknown analysis stage: {stage}")
        current = self._state.analysis_stage
        if current not in ordered:
            raise ValueError(f"Invalid current analysis stage: {current}")
        if ordered.index(stage) < ordered.index(current):
            raise ValueError(f"Analysis stage regression: {current}->{stage}")
        if ordered.index(stage) > ordered.index(current) + 1:
            raise ValueError(f"Analysis stage skip is forbidden: {current}->{stage}")
        new_state = AlinaPhaseState(
            schema_version=self._state.schema_version,
            phase="ANALYZE",
            epoch=self._state.epoch,
            requested_at_utc=self._state.requested_at_utc,
            collection_started_at_utc=self._state.collection_started_at_utc,
            collection_cutoff_at_utc=self._state.collection_cutoff_at_utc,
            source_collection_epoch=self._state.source_collection_epoch,
            analysis_stage=stage,
            requested_by=self._state.requested_by,
            request_id=self._state.request_id,
        )
        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()
        return self._state
