"""Scope des profils GitHub externes + double verrou de matérialisation.

Objectif produit: le bus complet ("34 moteurs actifs") n'est plus le mode
normal. Par défaut seuls les repos de la matrice de distillation sont évalués,
et la matérialisation directe exige DEUX flags explicites.
"""

from __future__ import annotations

from hl_observer.copy_wallet.copy_conflict_resolver import CopyConflictDecision
from hl_observer.strategies import external_simulation_bus as bus
from hl_observer.strategies.external_github_bridge import ExternalRepoCapability
from hl_observer.strategies.github_distillation import priority_distillation_matrix
from hl_observer.strategies.models import StrategyKind, make_strategy
from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
from hl_observer.ui.state import UiState

PRIORITY_REPO = "17_rezzecup_whale_wallet_mirror_copy_trader"
NON_PRIORITY_REPO = "12_polybot"


def _capability(local_id: str) -> ExternalRepoCapability:
    return ExternalRepoCapability(
        local_id=local_id,
        url=f"https://example.invalid/{local_id}",
        family="copy_trading",
        priority=1,
        role="research",
        installed=True,
        status="CLONED",
        path=f"/tmp/{local_id}",
        branch="main",
        commit="deadbeef",
        file_count=1,
        size_bytes=1,
        unavailable_reason="",
        target_modules=("hl_observer.copying",),
        profile_ids=(f"ext_{local_id}",),
    )


def _definition(repo_id: str) -> object:
    return make_strategy(
        strategy_id=f"ext_{repo_id}",
        version=1,
        kind=StrategyKind.COPY_FOLLOW,
        name=repo_id,
        tags=("external-github-priority", "copy_trading"),
        params={"source_local_id": repo_id, "source_status": "CLONED"},
    )


def _empty_conflict() -> CopyConflictDecision:
    return CopyConflictDecision(
        coin="",
        decision="NO_MAJORITY",
        winning_side=None,
        long_score=0.0,
        short_score=0.0,
        reasons=("TEST_EMPTY",),
    )


def _run_bus(monkeypatch) -> tuple:
    monkeypatch.setattr(
        bus,
        "external_strategy_definitions",
        lambda: (_definition(PRIORITY_REPO), _definition(NON_PRIORITY_REPO)),
    )
    monkeypatch.setattr(
        bus,
        "discover_external_repo_capabilities",
        lambda: (_capability(PRIORITY_REPO), _capability(NON_PRIORITY_REPO)),
    )
    return bus.run_external_profile_simulation_bus(
        leader_votes=(),
        conflict=_empty_conflict(),
        price_discrepancies=(),
        funding_signals=(),
        triangular_opportunities=(),
        maker_quotes=(),
        paper_orders=(),
    )


def test_default_scope_is_OFF_the_github_bus_is_retired(monkeypatch):
    """DECISION PRODUIT (Flo, 2026-07-12) : le bus GitHub est termine.

    Ce test disait l'inverse : il EXIGEAIT que le defaut soit "priority" -- autrement dit que le
    bus tourne. C'est exactement pour ca qu'il tournait encore, des mois apres avoir ete juge et
    ecarte (PF net 0,61). Un moteur abandonne doit etre eteint DANS LE CODE, pas dans les tetes.

    Les clones de recherche restent intacts ; c'est le CABLAGE runtime qui disparait."""
    monkeypatch.delenv(bus.PROFILE_SCOPE_ENV, raising=False)
    assert bus.external_profile_scope() == "off"


def test_scope_priority_still_works_when_asked_EXPLICITLY(monkeypatch):
    """On n'a rien supprime : la recherche reste possible. Mais elle se DEMANDE."""
    monkeypatch.setenv(bus.PROFILE_SCOPE_ENV, "priority")
    executions = _run_bus(monkeypatch)
    assert {row.repo_id for row in executions} == {PRIORITY_REPO}
    assert bus.external_profile_scope() == "priority"


def test_scope_all_restores_full_bus_for_local_research_only(monkeypatch):
    monkeypatch.setenv(bus.PROFILE_SCOPE_ENV, "all")
    executions = _run_bus(monkeypatch)
    repo_ids = {row.repo_id for row in executions}
    assert repo_ids == {PRIORITY_REPO, NON_PRIORITY_REPO}


def test_scope_off_evaluates_nothing(monkeypatch):
    monkeypatch.setenv(bus.PROFILE_SCOPE_ENV, "off")
    assert _run_bus(monkeypatch) == ()


def test_invalid_scope_falls_back_to_OFF_never_re_enables_the_bus(monkeypatch):
    """Une faute de frappe dans une variable d'env ne doit pas RALLUMER un moteur retire."""
    monkeypatch.setenv(bus.PROFILE_SCOPE_ENV, "everything")
    assert bus.external_profile_scope() == "off"


def test_priority_matrix_repo_ids_exist_in_bridge_specs():
    from hl_observer.strategies.external_github_bridge import requested_external_repos

    bridge_ids = {spec.local_id for spec in requested_external_repos()}
    for idea in priority_distillation_matrix():
        assert idea.repo_id in bridge_ids, f"repo prioritaire inconnu du bridge: {idea.repo_id}"


def _direct_copy_order() -> dict:
    return {
        "order_id": "ord-lock-1",
        "strategy_id": "ext_17_rezzecup_whale_wallet_mirror_copy_trader_profile",
        "accepted": True,
        "paper_only": True,
        "real_execution": False,
        "coin": "BTC",
        "side": "LONG",
        "notional_usdt": 25.0,
        "reference_price": 50_000.0,
        "metadata": {
            "source": "copy_conflict_resolver",
            "profile_family": "copy_trading",
            "edge_remaining_bps": 80.0,
            "signal_age_ms": 1_000.0,
            "leader_wallets_count": 4,
            "liquidity_score": 0.9,
            "copy_degradation_bps": 5.0,
            "all_in_cost_bps": 8.0,
        },
    }


def _fusion_status_with_direct_order() -> dict:
    return {
        "status": "OK_LIVE_FUSION_RUNTIME",
        "paper_only": True,
        "real_execution": False,
        "runtime": {
            "session": {"session_id": "lock-test"},
            "external_profile_executions": [],
            "paper_orders": [_direct_copy_order()],
            "paper_engine": {"decisions": []},
        },
        "paper_engine": {"decisions": []},
    }


def test_single_flag_no_longer_materializes_direct_orders(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.delenv("HYPERSMART_AB_RESEARCH_ACK", raising=False)
    state = UiState()
    report = apply_fusion_paper_orders_to_state(state, _fusion_status_with_direct_order(), current_ms=1_000)
    assert report["applied_count"] == 0
    assert report["external_direct_orders_shadowed"] == 1
    assert "EXTERNAL_DIRECT_REQUIRES_AB_RESEARCH_ACK" in report["reasons"]
    assert state.simulation_virtual_positions == {}


def test_both_flags_allow_ab_research_materialization(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
    state = UiState()
    report = apply_fusion_paper_orders_to_state(state, _fusion_status_with_direct_order(), current_ms=1_000)
    assert report["applied_count"] == 1
    assert len(state.simulation_virtual_positions) == 1
    position = next(iter(state.simulation_virtual_positions.values()))
    assert position["paper_only"] is True
    assert position["external_action"] is False
