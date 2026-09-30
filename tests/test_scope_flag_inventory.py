from __future__ import annotations

from pathlib import Path

from hl_observer.ops.entrypoint_topology import ENTRYPOINT_ROLES, EntrypointRole
from hl_observer.ops.scope_flag_inventory import (
    FlagDisposition,
    SCOPE_FLAG_RECORDS,
    audit_scope_flag_inventory,
    classified_entrypoints,
    discover_scope_relevant_defaults,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v5_disposition_taxonomy_is_exact() -> None:
    assert {item.value for item in FlagDisposition} == {
        "ACTIVE",
        "LEGACY_COMPAT",
        "DEAD",
        "HISTORICAL_COMMENT_ONLY",
        "AMBIGUOUS",
    }


def test_every_scope_relevant_env_default_is_explicitly_classified() -> None:
    discovered = discover_scope_relevant_defaults(ROOT / ".env.example")
    assert discovered
    assert set(discovered) == set(SCOPE_FLAG_RECORDS)
    assert all(record.disposition is not FlagDisposition.AMBIGUOUS for record in SCOPE_FLAG_RECORDS.values())


def test_execution_expanding_flags_are_locked_fail_closed() -> None:
    for name in (
        "HL_ENABLE_MAINNET_EXECUTION",
        "HL_ENABLE_TESTNET_EXECUTION",
        "REAL_MAINNET_TRADING",
        "TESTNET_MODE",
        "TESTNET_EXECUTION_ENABLED",
        "CONFIRM_TESTNET_EXECUTION",
        "ALLOW_MAINNET_ORDER_SUBMISSION",
        "HYPERSMART_ENABLE_EXECUTION",
        "HYPERSMART_ENABLE_TESTNET_EXECUTION",
        "HYPERSMART_ALLOW_MAINNET",
        "HYPERSMART_REAL_ORDERS_ENABLED",
        "HYPERSMART_EXCHANGE_ENDPOINT_ENABLED",
        "HYPERSMART_SIGNATURES_ENABLED",
        "HYPERSMART_WALLET_CONNECT_ENABLED",
    ):
        record = SCOPE_FLAG_RECORDS[name]
        assert record.required_safe_default in {"0", "false"}
        assert record.may_expand_execution is True
        assert record.authoritative_for_strategy_scope is False


def test_strategy_scope_modes_cannot_be_overridden_to_live() -> None:
    assert SCOPE_FLAG_RECORDS["HL_ENV"].required_safe_default == "paper"
    assert SCOPE_FLAG_RECORDS["HYPERSMART_MODE"].required_safe_default == "RESEARCH_ONLY"
    assert SCOPE_FLAG_RECORDS["HYPERSMART_RUNTIME_MODE"].required_safe_default == "paper"
    assert all(
        not record.authoritative_for_strategy_scope for record in SCOPE_FLAG_RECORDS.values()
    )


def test_entrypoint_topology_maps_to_v5_dispositions_without_ambiguity() -> None:
    mapped = classified_entrypoints()
    assert set(mapped) == set(ENTRYPOINT_ROLES)
    assert all(value is not FlagDisposition.AMBIGUOUS for value in mapped.values())
    for name, role in ENTRYPOINT_ROLES.items():
        if role in {
            EntrypointRole.OFFICIAL_RUNTIME,
            EntrypointRole.OFFICIAL_ANALYSIS,
            EntrypointRole.OFFICIAL_RESEARCH,
        }:
            assert mapped[name] is FlagDisposition.ACTIVE
        elif role in {EntrypointRole.MAINTENANCE, EntrypointRole.COMPAT}:
            assert mapped[name] is FlagDisposition.LEGACY_COMPAT
        elif role is EntrypointRole.LEGACY:
            assert mapped[name] is FlagDisposition.DEAD
        elif role is EntrypointRole.ARCHIVE:
            assert mapped[name] is FlagDisposition.HISTORICAL_COMMENT_ONLY


def test_repository_scope_inventory_has_no_ambiguity_or_unsafe_default() -> None:
    assert audit_scope_flag_inventory(ROOT) == []
