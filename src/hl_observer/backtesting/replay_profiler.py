"""CPU-only diagnostics for large deterministic Copy-Vault replays.

This module measures the existing replay engine without changing its semantics.
It is intentionally diagnostic: it never produces an economic verdict, enables
execution, or substitutes synthetic records for missing observations.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
import hashlib
import json
from time import perf_counter

from .replay_engine import replay_events_with_delay


def _output_digest(rows: Iterable[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def profile_replay_events(
    events: Iterable[dict[str, object]],
    *,
    delay_seconds: float,
    clock: Callable[[], float] = perf_counter,
) -> dict[str, object]:
    """Profile the canonical replay while proving that no event was lost.

    The iterable is materialized once so generators and lists follow the same
    path.  The injected clock is only for deterministic tests; production uses
    ``perf_counter``.  A backwards clock is rejected instead of emitting a
    misleading duration.
    """
    source = tuple(events)
    started = float(clock())
    replayed = replay_events_with_delay(source, delay_seconds=delay_seconds)
    finished = float(clock())
    elapsed_seconds = finished - started
    if elapsed_seconds < 0:
        raise ValueError("profile clock moved backwards")

    source_ids = tuple(sorted(row["event_id"].strip() for row in source))
    replay_ids = tuple(sorted(row["event_id"].strip() for row in replayed))
    count_preserved = len(source) == len(replayed)
    identities_preserved = source_ids == replay_ids
    exactness_preserved = count_preserved and identities_preserved
    return {
        "status": "VERIFIED" if exactness_preserved else "UNMEASURABLE",
        "input_events": len(source),
        "output_events": len(replayed),
        "elapsed_ms": elapsed_seconds * 1_000.0,
        "count_preserved": count_preserved,
        "event_id_multiset_preserved": identities_preserved,
        "exactness_preserved": exactness_preserved,
        "output_sha256": _output_digest(replayed),
    }


__all__ = ["profile_replay_events"]
