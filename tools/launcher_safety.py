"""Static safety audit for the repository's Windows launchers.

The audit is deliberately local and read-only: it inspects launcher text and
never executes a launcher, downloads a runtime, or changes repository state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path


_FORBIDDEN = (
    re.compile(r"git\s+push\s+--force(?:\s|$)", re.IGNORECASE),
    re.compile(r"git\s+reset\s+--hard", re.IGNORECASE),
    re.compile(r"git\s+clean\s+-", re.IGNORECASE),
    re.compile(r"\b(?:curl|wget|bitsadmin)\b.*(?:orders|trading|sign)", re.IGNORECASE),
)


def audit_launcher_file(path: str | Path) -> dict[str, object]:
    """Audit one launcher without running it or modifying it."""
    candidate = Path(path)
    try:
        text = candidate.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return {"path": str(candidate), "status": "REJECTED", "reason": type(exc).__name__}
    upper = text.upper()
    forbidden = [pattern.pattern for pattern in _FORBIDDEN if pattern.search(text)]
    name = candidate.name.upper()
    if name == "LANCER_COLLECTEURS_COPY_VAULT.CMD":
        required = ("HL_ENABLE_MAINNET_EXECUTION=0", "HL_ENABLE_TESTNET_EXECUTION=0", "TESTNET_ONLY=TRUE")
    elif name == "LANCER_LAB_QUANT_COPY_VAULT.CMD":
        required = ("HL_ENABLE_MAINNET_EXECUTION=0", "HL_ENABLE_TESTNET_EXECUTION=0", "PAPER / READ-ONLY")
    elif name == "LANCER_HYPERSMART.CMD":
        required = ("HL_ENABLE_MAINNET_EXECUTION=0", "HL_ENABLE_TESTNET_EXECUTION=0", "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW")
    elif name == "POUSSER-GITHUB-FORCE.CMD":
        required = ("AUCUN PUSH FORCE", "AUCUN TELECHARGEMENT DE SHARDS")
    elif name == "ALINA_SYNC_COMPLETE.CMD":
        required = ("DOWNLOAD_AND_UNPACK_ALL_SAFE", "SYNC_COMPLETE_CLONE.PY")
    else:
        required = ()
    missing = [marker for marker in required if marker not in upper]
    has_exit = "EXIT /B" in upper
    valid = candidate.is_file() and not forbidden and not missing and has_exit
    return {
        "path": str(candidate),
        "status": "PROVEN" if valid else "REJECTED",
        "paper_read_only": True,
        "real_execution": False,
        "forbidden_operations": forbidden,
        "missing_safe_markers": missing,
        "exit_code_propagated": has_exit,
        "mutation": False,
    }


def launcher_safety_receipt(paths: Iterable[str | Path]) -> dict[str, object]:
    """Return a fail-closed receipt for a complete launcher inventory."""
    rows = [audit_launcher_file(path) for path in paths]
    valid = bool(rows) and all(row.get("status") == "PROVEN" for row in rows)
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "verdict": "LAUNCHERS_PAPER_SAFE" if valid else "LAUNCHERS_UNSAFE",
        "paper_read_only": True,
        "real_execution": False,
        "mutation": False,
        "launcher_count": len(rows),
        "launchers": rows,
        "fail_closed": not valid,
    }


__all__ = ["audit_launcher_file", "launcher_safety_receipt"]
