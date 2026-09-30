from pathlib import Path


WORKFLOW = Path(".github/workflows/cablage-drift-diagnostic.yml")


def test_cablage_drift_diagnostic_tracks_python_source_changes() -> None:
    """The wiring-drift diagnostic must run when production Python can change."""
    text = WORKFLOW.read_text(encoding="utf-8")

    assert '- "src/**/*.py"' in text
    assert '- "tests/test_risk_guards_no_limbo.py"' in text
