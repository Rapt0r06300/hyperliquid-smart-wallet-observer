"""Mirror candidate facade.

The existing active implementation lives in ``hl_observer.copy_mode``. This
module exposes the requested ``copy_wallet`` namespace without duplicating the
core dataclass or breaking existing imports.
"""

from __future__ import annotations

from hl_observer.copy_mode.wallet_mirror_runtime import (
    MirrorCandidate,
    MirrorRuntimeConfig,
    candidate_to_paper_intent,
    mirror_candidate_from_delta,
)

__all__ = [
    "MirrorCandidate",
    "MirrorRuntimeConfig",
    "candidate_to_paper_intent",
    "mirror_candidate_from_delta",
]
