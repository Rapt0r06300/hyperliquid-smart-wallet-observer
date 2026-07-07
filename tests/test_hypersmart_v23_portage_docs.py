from pathlib import Path


def test_v23_portage_docs_exist_and_link_to_tested_modules() -> None:
    required = [
        Path("docs/research/HYPERSMART_V23_LICENSE_AND_PORTAGE_AUDIT.md"),
        Path("docs/research/HYPERSMART_V23_SOURCE_TO_TARGET_FILE_MAP.md"),
        Path("docs/research/HYPERSMART_V23_MODULE_PORTAGE_MATRIX.md"),
        Path("docs/research/HYPERSMART_V23_GITHUB_ENGINE_MATRIX.md"),
        Path("docs/research/HYPERSMART_V23_ENGINE_CONFLICT_RESOLUTION.md"),
    ]
    for path in required:
        text = path.read_text(encoding="utf-8")
        assert "Paper" in text or "paper" in text
        assert "real_execution" in text or "Real external trading" in text or "vraie" in text.lower()

    matrix = required[2].read_text(encoding="utf-8")
    assert "tests/test_refactor_fusion_wallet_copy_e2e.py" in matrix
    assert "tests/test_refactor_fusion_arbitrage_e2e.py" in matrix
    assert "tests/test_refactor_fusion_funding_e2e.py" in matrix
    assert "tests/test_refactor_fusion_backtest_e2e.py" in matrix
