from pathlib import Path


WORKFLOW = Path(".github/workflows/alina-github-dataset-job.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_legacy_dataset_job_is_manual_only() -> None:
    text = _text()
    preamble = text.split("jobs:", 1)[0]
    assert "alina-github-dataset-job-legacy-disabled" in preamble
    assert "workflow_dispatch:" in preamble
    assert "push:" not in preamble
    assert "schedule:" not in preamble
    assert "pull_request:" not in preamble


def test_legacy_dataset_job_is_unreachable_and_github_hosted() -> None:
    text = _text()
    assert "if: ${{ false }}" in text
    assert "runs-on: ubuntu-latest" in text
    assert "runs-on: [self-hosted" not in text


def test_legacy_dataset_job_has_minimal_permissions_and_no_secret() -> None:
    text = _text()
    assert "permissions:\n  contents: read" in text
    assert "secrets." not in text
    assert "TOKEN" not in text
    assert "upload-artifact" not in text
    assert "contents: write" not in text


def test_legacy_dataset_job_points_only_to_canonical_v2() -> None:
    text = _text()
    assert "legacy hypersmart-datasets source has been deleted" in text
    assert "Alina Dataset V2 is the only permitted dataset source" in text
    assert "Rapt0r06300/alina-smartflow-datasets-v2" in text
    assert "exit 1" in text


def test_legacy_dataset_job_cannot_collect_or_publish_data() -> None:
    text = _text()
    forbidden = (
        "--stream-assets",
        "--start-collection",
        "git push",
        "cp -a",
        "hl_observer.datasets",
        "ALINA_DATASET_HOME",
    )
    for needle in forbidden:
        assert needle not in text
