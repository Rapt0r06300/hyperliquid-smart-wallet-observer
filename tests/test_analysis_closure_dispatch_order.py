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
    for field, expression in (
        ("ALINA_PHASE", "steps.phase.outputs.phase"),
        ("ALINA_STAGE", "steps.phase.outputs.stage"),
        ("ALINA_EPOCH", "steps.phase.outputs.epoch"),
        (
            "ALINA_SOURCE_COLLECTION_EPOCH",
            "steps.phase.outputs.source_collection_epoch",
        ),
        ("ALINA_COLLECTION_CUTOFF_UTC", "steps.phase.outputs.cutoff"),
        ("ALINA_JOB_OUTCOME", "job.status"),
        ("ALINA_BUILD_OUTCOME", "steps.build_closure.outcome"),
        ("ALINA_PUBLISH_OUTCOME", "steps.publish_closure.outcome"),
        (
            "ALINA_PUBLISH_CHANGED",
            "steps.publish_closure.outputs.published",
        ),
        ("ALINA_DISPATCH_OUTCOME", "steps.dispatch_analysis.outcome"),
    ):
        assert f"{field}: ${{{{ {expression} }}}}" in summary


def test_global_closure_revalidates_phase_snapshot_before_each_build_and_publish() -> None:
    workflow = Path(
        ".github/workflows/global-implementation-closure.yml"
    ).read_text(encoding="utf-8")
    assert '"tools/verify_global_closure_phase.py"' in workflow
    assert '"tools/summarize_global_closure_run.py"' in workflow

    for step_id in ("build_closure", "publish_closure"):
        step = workflow.split(f"      - id: {step_id}\n", 1)[1].split("      - id:", 1)[0]
        assert "python tools/verify_global_closure_phase.py" in step
        for expected_field in (
            "ALINA_EXPECTED_PHASE",
            "ALINA_EXPECTED_STAGE",
            "ALINA_EXPECTED_EPOCH",
            "ALINA_EXPECTED_SOURCE_COLLECTION_EPOCH",
            "ALINA_EXPECTED_CUTOFF",
        ):
            assert expected_field in step

    publish = workflow.split("      - id: publish_closure\n", 1)[1].split(
        "      - id:", 1
    )[0]
    assert publish.count("python tools/verify_global_closure_phase.py") == 2
    assert 'echo "published=false" >> "$GITHUB_OUTPUT"' in publish
    assert 'echo "published=true" >> "$GITHUB_OUTPUT"' in publish
    summary = workflow.split("      - id: summarize_run\n", 1)[1]
    assert "ALINA_PUBLISH_CHANGED: ${{ steps.publish_closure.outputs.published }}" in summary
