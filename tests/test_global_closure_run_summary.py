from tools.summarize_global_closure_run import classify_run, main, render_summary


def test_collect_success_is_not_reported_as_a_closure() -> None:
    result = classify_run(
        phase="COLLECT",
        stage="",
        epoch="8",
        job_outcome="success",
        build_outcome="skipped",
        publish_outcome="skipped",
    )

    assert result["classification"] == "NOT_A_CLOSURE_RUN"
    assert result["receipt_published"] is False
    assert result["economic_proof"] is False
    summary = render_summary(
        result,
        phase="COLLECT",
        stage="",
        epoch="8",
        source_collection_epoch="",
        cutoff="",
        build_outcome="skipped",
        publish_outcome="skipped",
        dispatch_outcome="skipped",
        job_outcome="success",
        commit_sha="abc123",
        run_id="42",
    )
    assert "NOT_A_CLOSURE_RUN" in summary
    assert "Aucune preuve technique ou économique" in summary
    assert "Build receipt : `skipped`" in summary


def test_early_analysis_stage_is_not_a_closure() -> None:
    result = classify_run(
        phase="ANALYZE",
        stage="REPLAY",
        epoch="9",
        job_outcome="success",
        build_outcome="skipped",
        publish_outcome="skipped",
    )

    assert result["classification"] == "ANALYSIS_IN_PROGRESS_NOT_CLOSURE"
    assert result["receipt_published"] is False


def test_failed_or_incomplete_receipt_path_is_fail_closed() -> None:
    failed = classify_run(
        phase="ANALYZE",
        stage="SCOREBOARD",
        epoch="9",
        job_outcome="failure",
        build_outcome="success",
        publish_outcome="failure",
    )
    incomplete = classify_run(
        phase="ANALYZE",
        stage="SCOREBOARD",
        epoch="9",
        job_outcome="success",
        build_outcome="success",
        publish_outcome="skipped",
    )

    assert failed["classification"] == "CLOSURE_ATTEMPT_FAILED_NOT_PROVEN"
    assert incomplete["classification"] == "CLOSURE_INCOMPLETE_NOT_PROVEN"
    assert failed["receipt_published"] is False
    assert incomplete["receipt_published"] is False


def test_published_receipt_is_not_itself_economic_proof() -> None:
    result = classify_run(
        phase="ANALYZE",
        stage="DONE",
        epoch="9",
        job_outcome="success",
        build_outcome="success",
        publish_outcome="success",
    )

    assert result["classification"] == "RECEIPT_PUBLISHED_REQUIRES_REVIEW"
    assert result["receipt_published"] is True
    assert result["economic_proof"] is False


def test_unrecognized_phase_or_epoch_is_not_a_proof() -> None:
    result = classify_run(
        phase="UNKNOWN",
        stage="",
        epoch="not-an-epoch",
        job_outcome="success",
        build_outcome="success",
        publish_outcome="success",
    )

    assert result["classification"] == "PHASE_UNVERIFIED_NOT_PROVEN"
    assert result["receipt_published"] is False


def test_cli_appends_a_run_summary(tmp_path, monkeypatch, capsys) -> None:
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setenv("ALINA_PHASE", "COLLECT")
    monkeypatch.setenv("ALINA_STAGE", "")
    monkeypatch.setenv("ALINA_EPOCH", "8")
    monkeypatch.setenv("ALINA_SOURCE_COLLECTION_EPOCH", "")
    monkeypatch.setenv("ALINA_COLLECTION_CUTOFF_UTC", "")
    monkeypatch.setenv("ALINA_JOB_OUTCOME", "success")
    monkeypatch.setenv("ALINA_BUILD_OUTCOME", "skipped")
    monkeypatch.setenv("ALINA_PUBLISH_OUTCOME", "skipped")
    monkeypatch.setenv("ALINA_DISPATCH_OUTCOME", "skipped")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")

    assert main() == 0
    summary = summary_path.read_text(encoding="utf-8")
    assert "NOT_A_CLOSURE_RUN" in summary
    assert "`COLLECT` / `8`" in summary
    assert "`abc123`" in summary
    assert "42" in summary
    assert capsys.readouterr().out == summary
