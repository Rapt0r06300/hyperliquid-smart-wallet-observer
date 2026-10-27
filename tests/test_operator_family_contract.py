from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from operator_family_contract import normalize_operator_family  # noqa: E402


def test_family_neutral_collection_can_collect_shared_copy_vault_inputs() -> None:
    family, config = normalize_operator_family("start_collection", "all", {})

    assert family == "all"
    assert config["strategy_family"] == "all"


def test_nested_copy_vault_scope_is_used_when_selector_is_all() -> None:
    family, config = normalize_operator_family(
        "backtest", "all", {"strategy_family": "copy_vault", "capital_usd": 200}
    )

    assert family == "copy_vault"
    assert config == {"strategy_family": "copy_vault", "capital_usd": 200}


@pytest.mark.parametrize(
    "family",
    ["lead_lag", "cross_venue_dislocation", "cross_venue_dislocation_v2", "unknown"],
)
def test_out_of_scope_economic_family_is_refused(family: str) -> None:
    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        normalize_operator_family("backtest", family, {})


def test_family_neutral_collection_cannot_enable_another_economic_family() -> None:
    with pytest.raises(ValueError, match="DISABLED_BY_SCOPE"):
        normalize_operator_family("start_collection", "all", {"strategy_family": "lead_lag"})


def test_economic_all_expands_only_the_single_active_family() -> None:
    family, config = normalize_operator_family("backtest", "all", {})

    assert family == "copy_vault"
    assert config["strategy_family"] == "copy_vault"


def test_conflicting_explicit_and_nested_families_fail_closed() -> None:
    with pytest.raises(ValueError, match="OPERATOR_FAMILY_CONFLICT"):
        normalize_operator_family("backtest", "copy_vault", {"strategy_family": "lead_lag"})


def test_phase_control_intents_remain_family_neutral() -> None:
    assert normalize_operator_family("pause", "all", {})[0] == "all"
    assert normalize_operator_family("resume", "all", {})[0] == "all"

