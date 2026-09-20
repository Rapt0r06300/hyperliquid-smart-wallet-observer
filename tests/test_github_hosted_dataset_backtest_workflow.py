from pathlib import Path


WORKFLOW = Path(".github/workflows/alina-dataset-backtest-github.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_github_dataset_backtest_is_manual_and_github_hosted() -> None:
    text = _text()
    preamble = text.split("jobs:", 1)[0]
    assert "workflow_dispatch:" in preamble
    assert "schedule:" not in preamble
    assert "push:" not in preamble
    assert "pull_request:" not in preamble
    assert "runs-on: ubuntu-latest" in text
    assert "runs-on: [self-hosted" not in text
    assert "github.actor == 'Rapt0r06300'" in text


def test_github_dataset_backtest_requires_private_dataset_token() -> None:
    text = _text()
    assert "secrets.ALINA_DATASET_READ_TOKEN" in text
    assert "HYPERSMART_DATASET_TOKEN" in text
    assert "Rapt0r06300/hypersmart-datasets" in text
    assert "--release-id 371149058" in text


def test_github_dataset_backtest_is_paper_only() -> None:
    text = _text()
    required = (
        "HL_ENABLE_MAINNET_EXECUTION: '0'",
        "HL_ENABLE_TESTNET_EXECUTION: '0'",
        "REAL_MAINNET_TRADING: 'false'",
        "TESTNET_EXECUTION_ENABLED: 'false'",
        "HYPERSMART_ENABLE_REAL_ORDERS: '0'",
        "ENABLE_REAL_ORDERS: '0'",
        "HYPERSMART_ANALYSIS_LOCAL_ONLY: '1'",
        "--no-start-collection",
    )
    for needle in required:
        assert needle in text

    forbidden = (
        "REAL_MAINNET_TRADING: 'true'",
        "HL_ENABLE_MAINNET_EXECUTION: '1'",
        "HL_ENABLE_TESTNET_EXECUTION: '1'",
        "--start-collection",
        "/exchange",
    )
    lowered = text.lower()
    for needle in forbidden:
        assert needle.lower() not in lowered


def test_github_dataset_backtest_does_not_upload_raw_dataset() -> None:
    text = _text()
    assert '"raw_dataset_uploaded": false' in text
    assert "Build compact public-safe report bundle" in text
    assert "project_runtime_reports" in text
    assert "dataset_runtime_reports" in text
    assert "data/hypersmart_datasets/**" not in text
