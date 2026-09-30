from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_guard_explicitly_rejects_test_deletions():
    """Keep the pre-run anti-red-hiding guard explicit without wiring dead modules."""
    source = (ROOT / "src/hl_observer/ops/pre_run_final_546_775.py").read_text(
        encoding="utf-8"
    )

    assert '"git", "diff", "--name-status", "HEAD^", "HEAD", "--", "tests"' in source
    assert 'line.startswith("D\\t")' in source
