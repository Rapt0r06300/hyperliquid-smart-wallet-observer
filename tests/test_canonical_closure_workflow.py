from pathlib import Path


WORKFLOW = Path(".github/workflows/alina-canonical-closure-report.yml")


def test_canonical_closure_supersedes_stale_runs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "group: alina-canonical-closure-report" in text
    assert "cancel-in-progress: true" in text


def test_canonical_closure_rebuilds_from_latest_head_before_push() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    publish = text.split(
        "      - name: Publish closure report from latest canonical head\n", 1
    )[1]
    assert "for attempt in 1 2 3 4 5; do" in publish
    assert "git fetch origin main" in publish
    assert "git reset --hard origin/main" in publish
    assert "dataset-v2" not in publish
    assert "python tools/build_closure_report.py" in publish
    assert "--dataset-root ." in publish
    assert 'if git push origin HEAD:main; then' in publish


def test_canonical_closure_reacts_to_durable_evidence_changes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for path in (
        "catalog/DATA_METRICS.json",
        "catalog/DATASET_HEALTH_RECEIPT.json",
        "catalog/TRADE_COUNT_PATCH.json",
        "catalog/TRADE_UNIQUE_COUNT_PATCH.json",
        "catalog/RECORD_COUNT_PATCH.json",
        "catalog/UNCOMPRESSED_SIZE_PATCH.json",
        "catalog/CAMPAIGN_RESILIENCE_RECEIPT.json",
        "catalog/RESUME_SMOKE_RECEIPT.json",
        "catalog/COLLECT_RESUME_SMOKE_RECEIPT.json",
        "catalog/COLLECT_RESUME_PROBE_STATE.json",
        "catalog/GLOBAL_IMPLEMENTATION_CLOSURE.json",
        "catalog/ANALYSIS_SCOREBOARD_RECEIPT.json",
        "catalog/campaigns/**",
        "control/alina-phase.json",
    ):
        assert path in text
