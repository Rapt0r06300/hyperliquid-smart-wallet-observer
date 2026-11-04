"""Evidence gates for Copy-Vault scope, audit state and rejected inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def docs_scope_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require audit documents to name Copy-Vault as the sole active family."""
    if not rows:
        return _base("MORE_DATA", reason="empty_scope_docs")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("active_family") != "Copy-Vault"
        or row.get("active_family_count") != 1
        or row.get("fixed_multi_family_target") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="DOCS_COPY_VAULT_ONLY", invalid_rows=invalid)


def runbook_dynamic_target_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a frozen measurement protocol plus continued discovery."""
    if not rows:
        return _base("MORE_DATA", reason="empty_runbook_target")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fixed_target") is not False
        or row.get("freeze_protocol") is not True
        or row.get("continuous_discovery") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="RUNBOOK_DYNAMIC_TARGET_WITH_FREEZE", invalid_rows=invalid)


def canonical_spec_freeze_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require objectives to be edited in the canonical spec with a freeze contract."""
    if not rows:
        return _base("MORE_DATA", reason="empty_canonical_spec")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("canonical_spec") is not True
        or row.get("parallel_spec") is not False
        or row.get("target_fixed") is not False
        or row.get("freeze_contract") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CANONICAL_SPEC_FREEZE_ENFORCED", invalid_rows=invalid)


def objective_state_head_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require objective and current-state references to agree on one HEAD."""
    if not rows:
        return _base("MORE_DATA", reason="empty_objective_state_head")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("objective_sha") or "").strip()
        or row.get("objective_sha") != row.get("state_sha")
        or row.get("stale") is not False
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="OBJECTIVE_STATE_HEAD_ALIGNED", invalid_rows=invalid)


def certification_gate_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Separate proof gates from a fixed economic target."""
    if not rows:
        return _base("MORE_DATA", reason="empty_certification_gate")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("fixed_target") is not False
        or row.get("proof_gate") is not True
        or row.get("small_gain_allowed") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CERTIFICATION_GATES_TARGET_INDEPENDENT", invalid_rows=invalid)


def historical_tasklist_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mark old multi-family tasklists as historical and non-authoritative."""
    if not rows:
        return _base("MORE_DATA", reason="empty_historical_tasklist")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("historical") is not True
        or row.get("authoritative") is not False
        or not str(row.get("as_of") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="HISTORICAL_TASKLIST_NON_AUTHORITATIVE", invalid_rows=invalid)


def epoch_scoreboard_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Prevent a prior epoch scoreboard from being projected as current."""
    if not rows:
        return _base("MORE_DATA", reason="empty_epoch_scoreboard")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("current_epoch") != 8
        or row.get("scoreboard_epoch") == row.get("current_epoch")
        or row.get("projected_as_current") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="PRIOR_EPOCH_NOT_PROJECTED", invalid_rows=invalid)


def champion_nonmeasurable_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Represent absent champion evidence honestly without inventing a gain."""
    if not rows:
        return _base("MORE_DATA", reason="empty_champion_state")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("champion") is not None
        or row.get("status") != "NON_MEASURABLE"
        or row.get("gain_claimed") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CHAMPION_NON_MEASURABLE_HONEST", invalid_rows=invalid)


def partial_sample_exclusion_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep a partial sample classified and excluded until repaired."""
    if not rows:
        return _base("MORE_DATA", reason="empty_partial_sample")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("sample_id") != "45199"
        or row.get("status") != "PARTIAL"
        or row.get("included_in_replay") is not False
        or row.get("included_in_backtest") is not False
        or not str(row.get("classification") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="PARTIAL_SAMPLE_EXCLUDED_AND_CLASSIFIED", invalid_rows=invalid)


def rejected_inventory_exclusion_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require every rejected input to stay out of replay and backtest."""
    if not rows:
        return _base("MORE_DATA", reason="empty_rejected_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("status") != "REJECTED"
        or row.get("included_in_replay") is not False
        or row.get("included_in_backtest") is not False
        or not str(row.get("reason") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="REJECTED_INPUTS_EXCLUDED", invalid_rows=invalid)


__all__ = [
    "docs_scope_receipt",
    "runbook_dynamic_target_receipt",
    "canonical_spec_freeze_receipt",
    "objective_state_head_receipt",
    "certification_gate_receipt",
    "historical_tasklist_receipt",
    "epoch_scoreboard_receipt",
    "champion_nonmeasurable_receipt",
    "partial_sample_exclusion_receipt",
    "rejected_inventory_exclusion_receipt",
]
