from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRE_RUN = ROOT / ".github" / "workflows" / "pre-run-321-775.yml"
FINAL_V1 = ROOT / ".github" / "workflows" / "alina-self-hosted-final-v1.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pre_run_coverage_witness_has_big_run_wait_budget_without_weakening_proof() -> None:
    workflow = _text(PRE_RUN)

    assert "name: Réutiliser et revérifier la preuve coverage 100%" in workflow
    assert "timeout-minutes: 200" in workflow
    assert "for ATTEMPT in $(seq 1 720); do" in workflow
    assert "sleep 15" in workflow

    # The longer orchestration window must never weaken the actual 100% witness.
    assert "python tools/check_coverage_ratchet.py" in workflow
    assert "COVERAGE_GAPS_NOT_ZERO" in workflow
    assert "hypersmart/coverage-parallel-probe" in workflow
    assert "COVERAGE_PROBE_RED" in workflow
    assert "COVERAGE_PROBE_TIMEOUT" in workflow


def test_final_v1_waits_long_enough_for_same_sha_technical_gates() -> None:
    workflow = _text(FINAL_V1)

    assert "timeout-minutes: 1100" in workflow
    assert "$deadline = [DateTimeOffset]::UtcNow.AddMinutes(240)" in workflow
    assert "hypersmart/pre-run-775" in workflow
    assert "hypersmart/technical-perfect" in workflow
    assert "hypersmart/security-quality" in workflow
    assert "TECHNICAL_STATUS_NOT_GREEN" in workflow
    assert "SELF_HOSTED_STALE_SHA_REFUSED_DURING_WAIT" in workflow

    # Safety/read-only invariants remain explicit while long jobs wait.
    assert "HL_ENABLE_MAINNET_EXECUTION: '0'" in workflow
    assert "HL_ENABLE_TESTNET_EXECUTION: '0'" in workflow
    assert "HYPERSMART_ENABLE_REAL_ORDERS: '0'" in workflow
    assert "ENABLE_REAL_ORDERS: '0'" in workflow
