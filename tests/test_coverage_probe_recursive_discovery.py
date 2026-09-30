from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_coverage_parallel_probe_discovers_nested_test_modules() -> None:
    """The 100% witness must execute test modules below nested test packages too."""
    workflow = (ROOT / ".github" / "workflows" / "coverage-parallel-probe.yml").read_text(
        encoding="utf-8"
    )

    assert 'Path("tests").rglob("test_*.py")' in workflow
    assert 'Path("tests").glob("test_*.py")' not in workflow
