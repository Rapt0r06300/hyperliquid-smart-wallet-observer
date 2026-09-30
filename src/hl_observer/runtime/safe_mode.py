"""Runtime safe-mode flag for local simulation."""

from __future__ import annotations


def is_safe_mode_enabled(mode: str | None = None) -> bool:
    return str(mode or "LOCAL_RESEARCH_SIMULATION_ONLY").upper() != "REAL_EXECUTION"


__all__ = ["is_safe_mode_enabled"]
