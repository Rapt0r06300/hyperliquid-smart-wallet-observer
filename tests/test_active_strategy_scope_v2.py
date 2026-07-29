from __future__ import annotations

from pathlib import Path

from hl_observer.realtime.multi_source_price_stream import PriceEvent
from hl_observer.strategies.active_scope import (
    StrategyScopeStatus,
    active_strategy_families,
    authoritative_strategy_scope,
    strategy_can_materialize,
    strategy_scope_payload,
    strategy_scope_status,
)
from hl_observer.strategies.fusion_runtime import (
    FusionRuntimeInput,
    run_fusion_strategy_runtime,
)

ROOT = Path(__file__).resolve().parents[1]
STABLE_HIGH_FUNDING = (
    0.00049,
    0.00051,
    0.0005,
    0.00052,
    0.00048,
    0.0005,
    0.00051,
    0.00049,
    0.0005,
    0.00052,
    0.00048,
    0.0005,
)


def _funding_input() -> FusionRuntimeInput:
    return FusionRuntimeInput(
        session_id="v2-scope-test",
        leader_votes=(),
        price_events=(PriceEvent("hyperliquid", "HYPE", 70.0, 70.05, 1_000_000),),
        funding_rows=({"coin": "HYPE", "rates": STABLE_HIGH_FUNDING},),
        triangular_edges=(),
        peak_equity=1_000.0,
        current_equity=1_000.0,
    )


def test_v2_scope_has_exactly_three_economic_families() -> None:
    assert active_strategy_families() == frozenset(
        {"cross_venue_dislocation", "lead_lag", "copy_vault"}
    )
    entries = authoritative_strategy_scope()
    assert len(entries) == len({entry.family for entry in entries})
    assert all(
        entry.materializes_paper_economics
        == (entry.status is StrategyScopeStatus.ACTIVE)
        for entry in entries
    )


def test_scope_is_deny_by_default_and_has_no_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_ACTIVE_STRATEGIES", "funding_carry,market_making")
    assert strategy_can_materialize("funding_carry") is False
    assert strategy_can_materialize("market_making") is False
    assert strategy_can_materialize("unknown_family") is False
    assert strategy_scope_status("unknown_family") is StrategyScopeStatus.DISABLED
    assert strategy_scope_payload()["environment_override_allowed"] is False


def test_official_runtime_blocks_funding_even_when_legacy_flag_is_forced(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_FUNDING_ARB_PAPER", "1")
    result = run_fusion_strategy_runtime(_funding_input())

    assert result.delta_neutral_positions == ()
    assert result.funding_payments == ()
    assert result.funding_arb["enabled"] is False
    assert result.funding_arb["requested_by_environment"] is True
    assert result.funding_arb["events"] == []
    assert not any("funding" in strategy_id.lower() for strategy_id in result.paper_order_strategy_ids)
    assert "STRATEGY_SCOPE_BLOCKED_FUNDING_CARRY" in result.no_trade_reasons


def test_official_runtime_never_runs_external_profile_bus(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_EXTERNAL_PROFILES_SCOPE", "all")
    result = run_fusion_strategy_runtime(_funding_input())

    assert result.external_profile_executions == ()
    assert result.external_profile_execution_summary["profiles_total"] == 0
    assert "STRATEGY_SCOPE_BLOCKED_EXTERNAL_GITHUB_PROFILES" in result.no_trade_reasons


def test_runtime_payload_exposes_authoritative_scope() -> None:
    payload = run_fusion_strategy_runtime(_funding_input()).as_dict()["strategy_scope"]
    assert payload["scope_version"] == "V2-20260729"
    assert payload["active_families"] == [
        "copy_vault",
        "cross_venue_dislocation",
        "lead_lag",
    ]


def test_official_launchers_do_not_reenable_funding_economics() -> None:
    cmd = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")
    ps1 = (ROOT / "tools" / "start_hypersmart_simulation.ps1").read_text(
        encoding="utf-8", errors="replace"
    )
    assert 'HYPERSMART_FUNDING_ARB_PAPER=0' in cmd
    assert 'HYPERSMART_FUNDING_ARB_PAPER=1' not in cmd
    assert '"HYPERSMART_FUNDING_ARB_PAPER", "0"' in ps1
    assert '"HYPERSMART_FUNDING_ARB_PAPER", "1"' not in ps1
