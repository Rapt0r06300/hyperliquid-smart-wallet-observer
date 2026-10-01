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
