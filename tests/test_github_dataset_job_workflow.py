from pathlib import Path


WORKFLOW = Path(".github/workflows/alina-github-dataset-job.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_dataset_job_only_triggers_on_dedicated_control_path() -> None:
    text = _text()
    preamble = text.split("jobs:", 1)[0]
    assert "push:" in preamble
    assert "branches: [main]" in preamble
    assert "control/github_dataset_jobs/*.json" in preamble
    assert "workflow_dispatch:" not in preamble
    assert "research/queue" not in text
    assert "control/alina_jobs" not in text
    assert "control/alina_final_jobs" not in text


def test_dataset_job_is_github_hosted_and_actor_gated() -> None:
    text = _text()
    assert "runs-on: ubuntu-latest" in text
    assert "runs-on: [self-hosted" not in text
    assert "github.actor == 'Rapt0r06300'" in text
    assert "github.repository == 'Rapt0r06300/hyperliquid-smart-wallet-observer'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "Exactly one changed file is required." in text
    assert "Control file must be newly added." in text


def test_dataset_job_uses_private_token_without_uploading_raw_data() -> None:
    text = _text()
    assert "secrets.ALINA_DATASET_READ_TOKEN" in text
    assert "HYPERSMART_DATASET_TOKEN" in text
    assert "raw_dataset_uploaded" in text
    assert '"raw_dataset_uploaded":False' in text
    assert '"dataset_paths_uploaded":False' in text
    assert '"dataset_reports_uploaded":False' in text
    assert "cp -a" not in text
    assert "Upload sanitized proof only" in text
    assert 'echo "ALINA_DATASET_HOME=$RUNNER_TEMP/alina-datasets" >> "$GITHUB_ENV"' in text


def test_dataset_job_enforces_paper_read_only_and_streaming() -> None:
    text = _text()
    required = (
        "HL_ENABLE_MAINNET_EXECUTION: '0'",
        "HL_ENABLE_TESTNET_EXECUTION: '0'",
        "REAL_MAINNET_TRADING: 'false'",
        "TESTNET_EXECUTION_ENABLED: 'false'",
        "HYPERSMART_ENABLE_REAL_ORDERS: '0'",
        "ENABLE_REAL_ORDERS: '0'",
        "HYPERSMART_ANALYSIS_LOCAL_ONLY: '1'",
        "--stream-assets",
        "--no-start-collection",
    )
    for needle in required:
        assert needle in text


def test_dataset_job_validates_control_before_private_token_gate() -> None:
    text = _text()
    validate = text.index("Validate and normalize control")
    token = text.index("Require private dataset token")
    assert validate < token
    assert "blocked_missing_dataset_token" in text
    assert "steps.analysis.outcome != 'skipped'" in text
