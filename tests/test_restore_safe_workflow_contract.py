from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_multi_venue_safe_workflow_binds_the_three_value_restore_plan() -> None:
    workflow = (ROOT / ".github" / "workflows" / "alina-restore-safe-regression.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("- name: Verify bounded multi-venue SAFE shards against Release bytes")
    end = workflow.find("\n      - name:", start + 1)
    step = workflow[start:] if end < 0 else workflow[start:end]

    assert "proof, rows, required = _load_replay_ready_plan(" in step
    assert "_, proof, rows, required = _load_replay_ready_plan(" not in step


def test_windows_safe_workflow_no_longer_calls_removed_git_wrapper_functions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "alina-restore-safe-regression.yml").read_text(
        encoding="utf-8"
    )

    assert "Prove every Git wrapper forwards all arguments" not in workflow
    assert "Invoke-Git" not in workflow
    assert "tests/test_push_github_safe_contract.py" in workflow


def test_windows_checkout_includes_workflow_source_used_by_contract_tests() -> None:
    workflow = (ROOT / ".github" / "workflows" / "alina-restore-safe-regression.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("  launcher-windows:")
    checkout = workflow.index("      - name: Checkout launcher and restore runtime", start)
    sparse_start = workflow.index("          sparse-checkout: |", checkout)
    sparse_end = workflow.index("\n      - name:", sparse_start)
    sparse_checkout = workflow[sparse_start:sparse_end]

    assert "            .github/workflows\n" in sparse_checkout


def test_fresh_clone_contract_is_exact_ref_and_sha_bound() -> None:
    workflow = (ROOT / ".github" / "workflows" / "alina-restore-safe-regression.yml").read_text(
        encoding="utf-8"
    )

    start = workflow.index("- name: Perform a real normal clone and verify complete Git objects")
    end = workflow.index("      - name: Exercise the one-file SAFE restore launcher", start)
    step = workflow[start:end]

    assert 'git clone --no-checkout --branch "$GITHUB_REF_NAME" --single-branch' in step
    assert 'git checkout -B "$GITHUB_REF_NAME" "$GITHUB_SHA"' in step
    assert 'git cat-file -e "${GITHUB_SHA}^{commit}"' in step
    assert 'test "$(git branch --show-current)" = "$GITHUB_REF_NAME"' in step
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in step
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" HEAD' not in step
