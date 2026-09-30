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


def test_final_v1_is_hard_disabled_as_a_historical_self_hosted_tombstone() -> None:
    workflow = _text(FINAL_V1)
    preamble = workflow.split("jobs:", 1)[0]
    assert "workflow_dispatch:" in preamble
    assert "push:" not in preamble
    assert "schedule:" not in preamble
    assert "runs-on: ubuntu-latest" in workflow
    assert "exit 1" in workflow
    assert "GitHub-hosted Alina SmartFlow workflows" in workflow
    assert "runs-on: [self-hosted" not in workflow.lower()

