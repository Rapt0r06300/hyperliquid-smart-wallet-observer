from __future__ import annotations

from pathlib import Path

from hl_observer.ops import preflight_lanceur as PF
from hl_observer.ops import runtime_contract as RC

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_contract_accepts_exact_preflight_profile():
    env = dict(RC.PREFLIGHT_RUNTIME_FLAGS)
    result = RC.verify_runtime_env(env)
    assert result.ok, result.detail


def test_child_environment_removes_inherited_permissive_controls():
    parent = {
        **RC.PREFLIGHT_RUNTIME_FLAGS,
        "HYPERSMART_ACTIVE_STRATEGIES": "lead_lag",
        "HL_ENABLE_MAINNET_EXECUTION": "1",
        "START_TESTNET_EXECUTION": "1",
        "PRIVATE_KEY": "must-not-cross-process-boundary",
        "KEEP_DIAGNOSTIC": "yes",
    }
    child = RC.build_safe_child_environment(parent)
    check = RC.verify_safe_child_environment(child)
    assert check.ok, check.detail
    assert child["KEEP_DIAGNOSTIC"] == "yes"
    assert "HYPERSMART_ACTIVE_STRATEGIES" not in child
    assert "START_TESTNET_EXECUTION" not in child
    assert "PRIVATE_KEY" not in child
    assert child["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert child["HL_ENABLE_TESTNET_EXECUTION"] == "0"
    assert child["REAL_MAINNET_TRADING"] == "false"


def test_child_environment_rejects_permissive_override_after_construction():
    child = RC.build_safe_child_environment({})
    child["HYPERSMART_ACTIVE_STRATEGIES"] = "lead_lag"
    check = RC.verify_safe_child_environment(child)
    assert not check.ok
    assert "HYPERSMART_ACTIVE_STRATEGIES=INHERITED_OVERRIDE" in check.detail


def test_runtime_contract_declares_one_copy_vault_launch_scope():
    assert RC.OFFICIAL_LAUNCH_CONTRACT["scope_family"] == "copy_vault"
    assert RC.OFFICIAL_LAUNCH_CONTRACT["scope_version"] == "COPY_VAULT_PAPER_V2"
    assert RC.OFFICIAL_LAUNCH_CONTRACT["hosted_controller"].endswith(".yml")


def test_runtime_parameter_consumer_inventory_is_canonical_and_present():
    consumers = {path for group in RC.RUNTIME_PARAMETER_CONSUMERS.values() for path in group}
    assert "tools/start_hypersmart_simulation.ps1" in consumers
    assert "src/hl_observer/strategies/active_scope.py" in consumers
    assert all((ROOT / path).is_file() for path in consumers)


def test_orchestration_boundary_keeps_launcher_and_quant_engine_distinct():
    boundary = RC.ORCHESTRATION_BOUNDARY
    assert boundary["launcher"] != boundary["quant_engine"]
    assert boundary["orchestrator"].endswith("start_hypersmart_simulation.ps1")
    assert boundary["paper_only"] is True


def test_runtime_contract_rejects_missing_or_legacy_v1_enabled():
    env = dict(RC.PREFLIGHT_RUNTIME_FLAGS)
    env.pop("HL_ENABLE_TESTNET_EXECUTION")
    env["HYPERSMART_ARB_DISLOCATION_PAPER"] = "1"
    result = RC.verify_runtime_env(env)
    assert not result.ok
    detail = result.detail
    assert "HL_ENABLE_TESTNET_EXECUTION=MISSING" in detail
    assert "HYPERSMART_ARB_DISLOCATION_PAPER='1'" in detail


def test_preflight_runtime_contract_is_hard_gate_when_enabled():
    env = dict(RC.PREFLIGHT_RUNTIME_FLAGS)
    env["HYPERSMART_ARB_DISLOCATION_PAPER"] = "1"
    check = PF.verifier_contrat_runtime(env=env)
    assert check.dur is True
    assert check.ok is False
    assert check.nom == "contrat-runtime"
    assert "HYPERSMART_ARB_DISLOCATION_PAPER" in check.detail


def test_preflight_rejoue_le_contrat_si_la_version_derivait():
    env = dict(RC.PREFLIGHT_RUNTIME_FLAGS)
    env["HYPERSMART_SCOPE_VERSION"] = "ancienne-version"
    check = PF.verifier_contrat_runtime(env=env)
    assert check.dur is True and check.ok is False
    assert "HYPERSMART_SCOPE_VERSION" in check.detail


def test_official_launcher_guards_each_entrypoint_and_sets_other_flags_once():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="strict")
    autopilot = text.split("\n:autopilot\n", 1)[1].split("\n:dispatch\n", 1)[0]
    dispatch = text.split("\n:dispatch\n", 1)[1]
    assignments = RC.parse_cmd_set_assignments(text)
    # Distinct entrypoints intentionally reassert all four paper-only controls.
    guarded = {"HL_ENV", "HL_ENABLE_MAINNET_EXECUTION", "HL_ENABLE_TESTNET_EXECUTION", "HYPERSMART_MODE"}
    for key, expected in RC.CRITICAL_RUNTIME_FLAGS.items():
        values = assignments.get(key)
        expected_values = [expected, expected] if key in guarded else [expected]
        assert values == expected_values, f"{key}: {values!r}, attendu {expected_values!r}"
        if key in guarded:
            assert RC.parse_cmd_set_assignments(autopilot).get(key) == [expected]
            assert RC.parse_cmd_set_assignments(dispatch).get(key) == [expected]


def test_legacy_cross_venue_v1_is_quarantined_and_v2_is_active():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="strict")
    assignments = RC.parse_cmd_set_assignments(text)
    assert assignments["HYPERSMART_ARB_DISLOCATION_PAPER"] == ["0"]
    assert assignments["HYPERSMART_EXPERIMENTAL_PAPER"] == ["1"]
    assert assignments["HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE"] == ["1"]
    assert assignments["HYPERSMART_FUNDING_ARB_PAPER"] == ["0"]
    assert assignments["HYPERSMART_CARRY_HYPE_PAPER"] == ["0"]
    assert assignments["HYPERSMART_CARRY_ETAPE2"] == ["0"]
    assert assignments["HYPERSMART_CARRY_DISABLED"] == ["1"]


def test_real_execution_flags_are_deny_by_default_in_contract():
    assert RC.CRITICAL_RUNTIME_FLAGS["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert RC.CRITICAL_RUNTIME_FLAGS["HL_ENABLE_TESTNET_EXECUTION"] == "0"
    assert RC.CRITICAL_RUNTIME_FLAGS["HL_ENV"] == "paper"


def test_cmd_parser_ignores_malformed_set_without_assignment():
    assignments = RC.parse_cmd_set_assignments('set "MALFORMED"\nset "HL_ENV=paper"\n')
    assert assignments == {"HL_ENV": ["paper"]}


def test_scope_rejects_inherited_strategy_widening():
    from hl_observer.strategies.active_scope import verify_official_runtime_scope

    ok, mismatches = verify_official_runtime_scope({"HYPERSMART_ACTIVE_STRATEGIES": "lead_lag"})
    assert not ok
    assert "override is forbidden" in mismatches[0]
