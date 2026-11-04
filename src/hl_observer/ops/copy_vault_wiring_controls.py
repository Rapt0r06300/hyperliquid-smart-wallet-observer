"""Fail-closed wiring and startup inventory controls for Copy-Vault."""

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


def required_module_wiring_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require every required module to be discoverable from the canonical runtime."""
    if not rows:
        return _base("MORE_DATA", reason="empty_required_module_wiring")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("module") or "").strip()
        or not str(row.get("import_path") or "").strip()
        or row.get("required") is not True
        or row.get("loaded") is not True
        or row.get("runtime") != "src.hl_observer"
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="REQUIRED_MODULE_WIRING_PROVEN", invalid_rows=invalid)


def tested_only_inventory_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep TESTE_SEULEMENT components explicit and unreachable from runtime."""
    if not rows:
        return _base("MORE_DATA", reason="empty_test_only_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("classification") != "TESTE_SEULEMENT"
        or row.get("runtime_reachable") is not False
        or not str(row.get("test_owner") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="TEST_ONLY_INVENTORY_EXPLICIT", invalid_rows=invalid)


def orphan_component_usage_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Make orphan status agree with an explicit usage list instead of guessing."""
    if not rows:
        return _base("MORE_DATA", reason="empty_component_usage_inventory")
    invalid = []
    for index, row in enumerate(rows):
        used_by = row.get("used_by") if isinstance(row, Mapping) else None
        orphan = row.get("orphan") if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("component") or "").strip() or not isinstance(used_by, list) or not isinstance(orphan, bool) or orphan == bool(used_by):
            invalid.append(index)
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="ORPHAN_COMPONENT_USAGE_EXPLICIT", invalid_rows=invalid)


def following_wallet_bridge_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require following events to resolve to consented wallet identities."""
    if not rows:
        return _base("MORE_DATA", reason="empty_following_wallet_bridge")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("following_event_id") or "").strip()
        or not str(row.get("wallet_id") or "").strip()
        or not str(row.get("provenance") or "").strip()
        or row.get("consent") is not True
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="FOLLOWING_WALLET_BRIDGE_PROVEN", invalid_rows=invalid)


def legacy_vs_canonical_runtime_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Prevent legacy compatibility surfaces from being treated as a second runtime."""
    if not rows:
        return _base("MORE_DATA", reason="empty_runtime_surface_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("canonical_runtime") not in {True, False}
        or row.get("surface") not in {"src.hl_observer", "hyper_smart_observer"}
        or (row.get("surface") == "src.hl_observer" and row.get("canonical_runtime") is not True)
        or (row.get("surface") == "hyper_smart_observer" and row.get("canonical_runtime") is not False)
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="LEGACY_AND_CANONICAL_DISTINCT", invalid_rows=invalid)


def concurrent_pipeline_import_scope_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require pipeline imports to remain inside the Copy-Vault canonical scope."""
    if not rows:
        return _base("MORE_DATA", reason="empty_pipeline_import_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("pipeline") or "").strip()
        or not str(row.get("import_path") or "").startswith("src.hl_observer")
        or row.get("family") != "Copy-Vault"
        or row.get("disabled_family_import") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CONCURRENT_PIPELINE_IMPORT_SCOPE_BOUNDED", invalid_rows=invalid)


def paper_intent_unification_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require one canonical PaperIntent identity with aliases only as compatibility labels."""
    if not rows:
        return _base("MORE_DATA", reason="empty_paper_intent_inventory")
    ids = [row.get("canonical_type_id") if isinstance(row, Mapping) else None for row in rows]
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("canonical_type_id") or "").strip()
        or row.get("canonical") is not True
        or row.get("duplicate_model") is not False
        or row.get("canonical_type_id") != ids[0]
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="PAPER_INTENT_CANONICAL_UNIFIED", invalid_rows=invalid)


def shared_stream_state_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require UI and poller to observe the same stream state epoch."""
    if not rows:
        return _base("MORE_DATA", reason="empty_shared_stream_state")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("ui_state") != row.get("poller_state")
        or row.get("ui_epoch") != row.get("poller_epoch")
        or not isinstance(row.get("ui_epoch"), int)
        or row.get("ui_epoch") < 0
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="UI_POLLER_SHARED_STREAM_STATE", invalid_rows=invalid)


def startup_module_tree_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a deterministic startup tree with one canonical orchestrator."""
    if not rows:
        return _base("MORE_DATA", reason="empty_startup_module_tree")
    orchestrators = [row for row in rows if isinstance(row, Mapping) and row.get("role") == "ORCHESTRATOR"]
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("path") or "").strip()
        or row.get("importable") is not True
        or row.get("startup_order") is None
    ]
    if len(orchestrators) != 1:
        invalid.append("orchestrator_count")
    return _base("PROVEN" if not invalid else "REJECTED", verdict="STARTUP_MODULE_TREE_BOUNDED", invalid_rows=invalid)


def canary_call_trace_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require canary traces to be paper/read-only and free of network execution calls."""
    if not rows:
        return _base("MORE_DATA", reason="empty_canary_call_trace")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("call") or "").strip()
        or row.get("mode") != "PAPER"
        or row.get("network_order_call") is not False
        or row.get("real_execution") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CANARY_CALL_TRACE_READ_ONLY", invalid_rows=invalid)


__all__ = [
    "required_module_wiring_receipt",
    "tested_only_inventory_receipt",
    "orphan_component_usage_receipt",
    "following_wallet_bridge_receipt",
    "legacy_vs_canonical_runtime_receipt",
    "concurrent_pipeline_import_scope_receipt",
    "paper_intent_unification_receipt",
    "shared_stream_state_receipt",
    "startup_module_tree_receipt",
    "canary_call_trace_receipt",
]
