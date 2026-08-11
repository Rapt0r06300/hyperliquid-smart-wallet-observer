from __future__ import annotations

from pathlib import Path

from hl_observer.ops import preflight_lanceur as PF
from hl_observer.ops import runtime_contract as RC

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_contract_accepts_exact_preflight_profile():
    env = dict(RC.PREFLIGHT_RUNTIME_FLAGS)
    result = RC.verify_runtime_env(env)
    assert result.ok, result.detail


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


def test_official_launcher_matches_every_critical_runtime_flag_once():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="strict")
    assignments = RC.parse_cmd_set_assignments(text)
    for key, expected in RC.CRITICAL_RUNTIME_FLAGS.items():
        values = assignments.get(key)
        assert values == [expected], f"{key}: {values!r}, attendu {[expected]!r}"


def test_legacy_cross_venue_v1_is_quarantined_and_v2_is_active():
    text = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="strict")
    assignments = RC.parse_cmd_set_assignments(text)
    assert assignments["HYPERSMART_ARB_DISLOCATION_PAPER"] == ["0"]
    assert assignments["HYPERSMART_EXPERIMENTAL_PAPER"] == ["1"]
    assert assignments["HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE"] == ["0"]
    assert assignments["HYPERSMART_FUNDING_ARB_PAPER"] == ["0"]
    assert assignments["HYPERSMART_CARRY_HYPE_PAPER"] == ["0"]
    assert assignments["HYPERSMART_CARRY_ETAPE2"] == ["0"]
    assert assignments["HYPERSMART_CARRY_DISABLED"] == ["1"]


def test_real_execution_flags_are_deny_by_default_in_contract():
    assert RC.CRITICAL_RUNTIME_FLAGS["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert RC.CRITICAL_RUNTIME_FLAGS["HL_ENABLE_TESTNET_EXECUTION"] == "0"
    assert RC.CRITICAL_RUNTIME_FLAGS["HL_ENV"] == "paper"
