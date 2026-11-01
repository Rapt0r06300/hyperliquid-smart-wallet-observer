"""Fail-closed H-T102 performance-comparison receipt validation.

The validator checks explicit receipt metadata only. It does not recompute a
gain, assume equal data because a field is absent, or turn a local fixture into
hosted evidence. Exact SHA/run/artifact binding remains the responsibility of
the generic closure gate.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PROVEN = "PROVEN"
NOT_PROVEN = "NOT_PROVEN"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CLAIMS = (
    "gain_reproducible",
    "semantic_equivalence",
    "same_dataset",
    "same_trials",
    "determinism_preserved",
    "coverage_preserved",
    "data_count_preserved",
    "trial_count_preserved",
    "costs_preserved",
)


def _sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value.lower()))


def _present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_performance_comparison_receipt(receipt: Mapping[str, Any] | object) -> dict[str, Any]:
    """Validate one explicit performance comparison without inferring values."""

    missing: list[str] = []
    invalid: list[str] = []
    if not isinstance(receipt, Mapping):
        return {
            "status": NOT_PROVEN,
            "missing": [],
            "invalid": ["receipt"],
            "claims": {},
            "paper_read_only": None,
            "real_execution": None,
        }

    def require(path: str, predicate: Any) -> Any:
        current: Any = receipt
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                missing.append(path)
                return None
            current = current[part]
        if not predicate(current):
            invalid.append(path)
        return current

    require("schema", lambda value: value == "hypersmart.copy_vault_performance_comparison_receipt.v1")
    require("status", lambda value: value == "COMPLETED")
    require("receipt_sha256", _sha256)
    paper_read_only = require("paper_read_only", lambda value: value is True)
    real_execution = require("real_execution", lambda value: value is False)
    require("comparison_context_sha256", _sha256)
    require("delta_usd_per_active_day", _present)

    claims = require("claims", lambda value: isinstance(value, Mapping))
    if isinstance(claims, Mapping):
        for claim in _CLAIMS:
            if claim not in claims:
                missing.append(f"claims.{claim}")
            elif claims[claim] is not True:
                invalid.append(f"claims.{claim}")

    for arm in ("baseline", "challenger"):
        value = require(arm, lambda item: isinstance(item, Mapping))
        if isinstance(value, Mapping):
            digest = value.get("receipt_sha256")
            path = f"{arm}.receipt_sha256"
            if digest is None:
                missing.append(path)
            elif not _sha256(digest):
                invalid.append(path)

    missing = list(dict.fromkeys(missing))
    invalid = list(dict.fromkeys(invalid))
    proven = not missing and not invalid
    return {
        "status": PROVEN if proven else NOT_PROVEN,
        "missing": missing,
        "invalid": invalid,
        "claims": {claim: True for claim in _CLAIMS} if proven else {},
        "paper_read_only": paper_read_only,
        "real_execution": real_execution,
    }


__all__ = ["NOT_PROVEN", "PROVEN", "validate_performance_comparison_receipt"]
