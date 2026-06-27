"""Process-shared CollectionRecorder (V12 — finalize #97/#98 activation).

A single process-global recorder so the collection path (which populates provenance)
and the dashboard (which reads source health) refer to the SAME instance. Within the
UI server process, collection triggered via safe_actions fills this recorder and the
dashboard reads it. Read-only bookkeeping; never an order, never fabricated data.
"""

from __future__ import annotations

from hl_observer.sources.collection_recorder import CollectionRecorder
from hl_observer.storage.run_context import RunContext

_SHARED: CollectionRecorder | None = None


def get_shared_recorder(*, context: RunContext = RunContext.LIVE) -> CollectionRecorder:
    global _SHARED
    if _SHARED is None:
        _SHARED = CollectionRecorder(context=context)
    return _SHARED


def set_shared_recorder(recorder: CollectionRecorder | None) -> None:
    global _SHARED
    _SHARED = recorder


def reset_shared_recorder() -> None:
    global _SHARED
    _SHARED = None


__all__ = ["get_shared_recorder", "set_shared_recorder", "reset_shared_recorder"]
