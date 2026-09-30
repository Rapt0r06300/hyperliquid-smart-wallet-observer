"""Wallet-copy fusion layer for the active ``src/hl_observer`` runtime.

The package ports copy-trader patterns into HyperSmart as paper-only building
blocks. It never submits a real order and never signs anything.
"""

from hl_observer.copy_wallet.mirror_candidate import MirrorCandidate, MirrorRuntimeConfig, mirror_candidate_from_delta
from hl_observer.copy_wallet.wallet_mirror_runtime import MirrorPipelineResult, run_wallet_mirror_pipeline

__all__ = [
    "MirrorCandidate",
    "MirrorPipelineResult",
    "MirrorRuntimeConfig",
    "mirror_candidate_from_delta",
    "run_wallet_mirror_pipeline",
]
