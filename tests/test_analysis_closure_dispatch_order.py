from pathlib import Path


def _advance_analysis_block() -> str:
    text = Path(".github/workflows/resumable-campaign-controller.yml").read_text(encoding="utf-8")
    marker = "  advance_analysis:\n"
    assert marker in text
    return text.split(marker, 1)[1]


def test_bounded_work_refreshes_closure_before_stage_advancement() -> None:
    block = _advance_analysis_block()
    assert "gh workflow run global-implementation-closure.yml" in block
    assert "gh workflow run analysis-stage-controller.yml" not in block


def test_global_closure_owns_followup_stage_dispatch() -> None:
    text = Path(".github/workflows/global-implementation-closure.yml").read_text(encoding="utf-8")
    assert "gh workflow run analysis-stage-controller.yml" in text


def test_done_does_not_dispatch_new_campaign_work() -> None:
    text = Path(".github/workflows/analysis-stage-controller.yml").read_text(encoding="utf-8")
    assert "steps.advance.outputs.new_stage != 'DONE'" in text
    assert "control/phase-receipts/**" in Path(
        ".github/workflows/global-implementation-closure.yml"
    ).read_text(encoding="utf-8")


def test_global_closure_reports_skipped_steps_as_non_proof() -> None:
    workflow = Path(".github/workflows/global-implementation-closure.yml").read_text(encoding="utf-8")
    assert "python tools/phase_gate.py read --state control/alina-phase.json" in workflow
    assert "id: build_closure" in workflow
    assert "id: publish_closure" in workflow
    assert "id: dispatch_analysis" in workflow
    summary = workflow.split("id: summarize_run", 1)[1]
    assert "if: always()" in summary
    assert "python tools/summarize_global_closure_run.py" in summary
    assert "ALINA_BUILD_OUTCOME: ${{ steps.build_closure.outcome }}" in summary
    assert "ALINA_PUBLISH_OUTCOME: ${{ steps.publish_closure.outcome }}" in summary
