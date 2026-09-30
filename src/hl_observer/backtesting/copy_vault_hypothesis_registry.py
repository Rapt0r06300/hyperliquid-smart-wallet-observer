"""Machine-enforced disposition ledger for Copy-Vault research hypotheses.

The registry is deliberately family-local. It prevents a hypothesis that was
explicitly killed from becoming runnable again just because an old selector or
name is referenced by a future research pack. Unknown hypotheses fail closed
until they receive an explicit reviewed disposition.

PAPER/READ-ONLY only; this module cannot submit or authorize execution.
"""
from __future__ import annotations

from typing import Final

KILLED_SIMPLE_WHITELIST: Final[str] = "copy_vault_simple_whitelist"
ACTIVE_CAUSAL_CONSENSUS: Final[str] = "copy_vault_vnext_causal_multiwallet_consensus"

_HYPOTHESES: Final[dict[str, dict[str, str]]] = {
    KILLED_SIMPLE_WHITELIST: {
        "hypothesis_id": KILLED_SIMPLE_WHITELIST,
        "status": "KILLED",
        "reason": "Simple wallet whitelist is superseded by entity-normalized robust TRAIN-only selection.",
        "replacement": ACTIVE_CAUSAL_CONSENSUS,
        "evidence_class": "HISTORICAL_NEGATIVE_EVIDENCE",
    },
    ACTIVE_CAUSAL_CONSENSUS: {
        "hypothesis_id": ACTIVE_CAUSAL_CONSENSUS,
        "status": "ACTIVE",
        "reason": "Current TRAIN-only causal multi-wallet consensus selector.",
        "replacement": "",
        "evidence_class": "CURRENT_RESEARCH_HYPOTHESIS",
    },
}


def copy_vault_hypothesis_disposition(hypothesis_id: str) -> dict[str, str]:
    """Return a defensive copy of one registered disposition."""

    key = str(hypothesis_id or "").strip()
    record = _HYPOTHESES.get(key)
    if record is None:
        return {
            "hypothesis_id": key,
            "status": "UNREGISTERED",
            "reason": "Hypothesis has no reviewed Copy-Vault disposition.",
            "replacement": "",
            "evidence_class": "NONE",
        }
    return dict(record)


def require_runnable_copy_vault_hypothesis(hypothesis_id: str) -> dict[str, str]:
    """Fail closed unless the exact Copy-Vault hypothesis is ACTIVE."""

    disposition = copy_vault_hypothesis_disposition(hypothesis_id)
    if disposition["status"] != "ACTIVE":
        raise RuntimeError(
            "Copy-Vault hypothesis is not runnable: "
            f"{disposition['hypothesis_id'] or '<empty>'} "
            f"status={disposition['status']}"
        )
    return disposition


def copy_vault_hypothesis_ledger() -> list[dict[str, str]]:
    """Return deterministic family-local hypothesis history for evidence bundles."""

    return [dict(_HYPOTHESES[key]) for key in sorted(_HYPOTHESES)]


__all__ = [
    "ACTIVE_CAUSAL_CONSENSUS",
    "KILLED_SIMPLE_WHITELIST",
    "copy_vault_hypothesis_disposition",
    "copy_vault_hypothesis_ledger",
    "require_runnable_copy_vault_hypothesis",
]
