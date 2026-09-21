"""Freeze contract for Event Intelligence OOS/forward research."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EventResearchFreeze:
    schema: str
    training_cutoff_ms: int
    created_at_ms: int
    config_sha256: str
    methodology_version: str
    paper_only: bool = True
    real_execution: bool = False


def freeze_event_research(
    config: Mapping[str, object],
    *,
    training_cutoff_ms: int,
    created_at_ms: int,
    methodology_version: str,
) -> EventResearchFreeze:
    payload = json.dumps(
        dict(config),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return EventResearchFreeze(
        schema="alina.event_research_freeze.v1",
        training_cutoff_ms=int(training_cutoff_ms),
        created_at_ms=int(created_at_ms),
        config_sha256=hashlib.sha256(payload).hexdigest(),
        methodology_version=str(methodology_version),
    )


def assert_forward_after_freeze(
    freeze: EventResearchFreeze,
    *,
    observation_ts_ms: int,
) -> None:
    if int(observation_ts_ms) <= int(freeze.training_cutoff_ms):
        raise ValueError("FORWARD_OBSERVATION_NOT_POST_FREEZE")


__all__ = [
    "EventResearchFreeze",
    "assert_forward_after_freeze",
    "freeze_event_research",
]
