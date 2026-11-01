"""Fail-closed validators for the two causal Copy-Vault evidence gaps.

These validators only inspect a caller-supplied receipt.  They do not collect
L4/LIVE_WS data, turn fixtures into production evidence, or change Agiflow
state.  A receipt is useful only when it explicitly proves the causal inputs
required by H-T115 or H-T170.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PROVEN = "PROVEN"
NOT_PROVEN = "NOT_PROVEN"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _equal(actual: object, expected: object) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    return actual == expected


def _claim_at_path(claims: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = claims
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _matches(actual: object, expected: object) -> bool:
    if isinstance(expected, Mapping):
        if "equals" in expected and not _equal(actual, expected["equals"]):
            return False
        if expected.get("present") is True and actual is None:
            return False
        if "min" in expected:
            try:
                if isinstance(actual, bool) or actual < expected["min"]:
                    return False
            except (TypeError, ValueError):
                return False
        return True
    return _equal(actual, expected)


def _validate(
    receipt: Mapping[str, Any] | object,
    *,
    task_id: str,
    schema: str,
    required_claims: Mapping[str, Any],
) -> dict[str, Any]:
    missing: list[str] = []
    if not isinstance(receipt, Mapping):
        return {
            "schema": schema,
            "task_id": task_id,
            "status": NOT_PROVEN,
            "missing_evidence": ["RECEIPT_NOT_OBJECT"],
        }
    if receipt.get("schema") != schema:
        missing.append("SCHEMA_MISMATCH")
    if receipt.get("completed") is not True:
        missing.append("RECEIPT_NOT_COMPLETED")
    digest = receipt.get("receipt_sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest.lower()):
        missing.append("RECEIPT_SHA256_MISSING_OR_INVALID")
    if receipt.get("paper_read_only") is not True:
        missing.append("PAPER_READ_ONLY_REQUIRED")
    if receipt.get("real_execution") is not False:
        missing.append("REAL_EXECUTION_MUST_BE_FALSE")
    claims = receipt.get("claims")
    if not isinstance(claims, Mapping):
        missing.append("CLAIMS_NOT_OBJECT")
        claims = {}
    for path, expected in required_claims.items():
        present, actual = _claim_at_path(claims, path)
        if not present:
            missing.append(f"CLAIM_MISSING:{path}")
        elif not _matches(actual, expected):
            missing.append(f"CLAIM_MISMATCH:{path}")
    missing = list(dict.fromkeys(missing))
    return {
        "schema": schema,
        "task_id": task_id,
        "status": PROVEN if not missing else NOT_PROVEN,
        "missing_evidence": missing,
        "paper_read_only": True,
        "real_execution": False,
    }


def validate_l4_pairing_receipt(receipt: Mapping[str, Any] | object) -> dict[str, Any]:
    """Validate H-T115's real L4/public-fill/SAFE-L2 pairing envelope."""

    return _validate(
        receipt,
        task_id="H-T115",
        schema="hypersmart.copy_vault_l4_pairing_receipt.v1",
        required_claims={
            "real_l4_session": True,
            "paired_public_fills": True,
            "paired_safe_l2": True,
            "point_in_time": True,
            "causal_coverage": {"min": 1},
            "provenance_by_provider_coin": True,
            "timestamps_present": True,
            "error_rates_present": True,
            "incremental_value": True,
        },
    )


def validate_live_ws_causal_receipt(receipt: Mapping[str, Any] | object) -> dict[str, Any]:
    """Validate H-T170's causal post-ACK LIVE_WS fill envelope."""

    return _validate(
        receipt,
        task_id="H-T170",
        schema="hypersmart.copy_vault_live_ws_causal_receipt.v1",
        required_claims={
            "causal_live_fill_rows": {"min": 1},
            "post_ack": True,
            "cutoff_epoch_present": True,
            "anti_double_count": True,
            "native_identity_reconciled": True,
            "snapshot_excluded_from_forward": True,
            "live_ws_provenance": True,
        },
    )


__all__ = [
    "NOT_PROVEN",
    "PROVEN",
    "validate_l4_pairing_receipt",
    "validate_live_ws_causal_receipt",
]
