from pathlib import Path


def test_release_docs_exist():
    required = [
        "docs/HYPERSMART_ARCHIVE_GUIDE.md",
        "docs/HYPERSMART_DATA_PIPELINE.md",
        "docs/HYPERSMART_EXPLORER_OBSERVER.md",
        "docs/HYPERSMART_WEBSOCKET_MONITOR.md",
        "docs/HYPERSMART_POSITION_LIFECYCLE.md",
        "docs/HYPERSMART_PATTERN_DETECTION.md",
        "docs/HYPERSMART_BACKTESTING.md",
        "docs/HYPERSMART_DASHBOARD.md",
        "docs/release/HYPERSMART_RELEASE_CANDIDATE_REPORT.md",
        "docs/release/HYPERSMART_TEST_MATRIX.md",
        "docs/release/HYPERSMART_SECURITY_GUARDRAILS.md",
    ]

    for file_name in required:
        assert Path(file_name).exists(), file_name
