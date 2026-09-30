"""Canonical Manual Phase Controller for Alina Smart Flow.

Owns control/alina-phase.json and manages state transitions: IDLE, COLLECT, ANALYZE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

CANONICAL_PHASE_PATH = Path("control/alina-phase.json")
ALLOWED_PHASES = frozenset({"IDLE", "COLLECT", "ANALYZE"})
ALLOWED_STAGES = frozenset({None, "DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE"})


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class AlinaPhaseState:
    phase: str = "IDLE"
    epoch: int = 1
    requested_at_utc: str = field(default_factory=_now_utc)
    collection_started_at_utc: str | None = None
    collection_cutoff_at_utc: str | None = None
    source_collection_epoch: int | None = None
    analysis_stage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AlinaPhaseState":
        if not isinstance(raw, dict):
            raise ValueError("Phase state must be a dict")
        phase = raw.get("phase")
        if phase not in ALLOWED_PHASES:
            raise ValueError(f"Invalid phase: {phase}")
        epoch = raw.get("epoch")
        if not isinstance(epoch, int) or epoch < 1:
            raise ValueError(f"Invalid epoch: {epoch}")
        stage = raw.get("analysis_stage")
        if stage not in ALLOWED_STAGES:
            raise ValueError(f"Invalid analysis stage: {stage}")
        return cls(
            phase=str(phase),
            epoch=int(epoch),
            requested_at_utc=str(raw.get("requested_at_utc", _now_utc())),
            collection_started_at_utc=raw.get("collection_started_at_utc"),
            collection_cutoff_at_utc=raw.get("collection_cutoff_at_utc"),
            source_collection_epoch=raw.get("source_collection_epoch"),
            analysis_stage=stage,
        )


def read_phase_state(path: Path = CANONICAL_PHASE_PATH) -> AlinaPhaseState:
    if not path.exists():
        state = AlinaPhaseState()
        write_phase_state(state, path)
        return state
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AlinaPhaseState.from_dict(data)
    except Exception as exc:
        raise ValueError(f"Fail-closed: unreadable phase file {path}: {exc}") from exc


def write_phase_state(state: AlinaPhaseState, path: Path = CANONICAL_PHASE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")


def transition_phase(target_phase: str, path: Path = CANONICAL_PHASE_PATH, *, now: str | None = None) -> AlinaPhaseState:
    target = target_phase.upper().strip()
    if target not in ALLOWED_PHASES:
        raise ValueError(f"Invalid phase transition target: {target_phase}")
    current = read_phase_state(path)
    now_ts = now or _now_utc()

    if target == current.phase:
        return current

    new_epoch = current.epoch + 1

    if target == "COLLECT":
        new_state = AlinaPhaseState(
            phase="COLLECT",
            epoch=new_epoch,
            requested_at_utc=now_ts,
            collection_started_at_utc=now_ts,
            collection_cutoff_at_utc=None,
            source_collection_epoch=None,
            analysis_stage=None,
        )
    elif target == "ANALYZE":
        source_epoch = current.epoch if current.phase == "COLLECT" else current.source_collection_epoch
        new_state = AlinaPhaseState(
            phase="ANALYZE",
            epoch=new_epoch,
            requested_at_utc=now_ts,
            collection_started_at_utc=current.collection_started_at_utc,
            collection_cutoff_at_utc=now_ts,
            source_collection_epoch=source_epoch,
            analysis_stage="DRAIN",
        )
    else:  # IDLE
        new_state = AlinaPhaseState(
            phase="IDLE",
            epoch=new_epoch,
            requested_at_utc=now_ts,
            collection_started_at_utc=None,
            collection_cutoff_at_utc=None,
            source_collection_epoch=None,
            analysis_stage=None,
        )

    write_phase_state(new_state, path)
    return new_state
