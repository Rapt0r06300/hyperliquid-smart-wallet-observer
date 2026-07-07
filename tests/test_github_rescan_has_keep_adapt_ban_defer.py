"""Section 8: the GitHub rescan doc classifies every repo KEEP/ADAPT/BAN/DEFER."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rescan_doc_has_classification_and_repos():
    doc = ROOT / "docs" / "research" / "HYPERSMART_GITHUB_RESCAN_CODEX.md"
    assert doc.exists(), "GitHub rescan doc missing"
    text = doc.read_text(encoding="utf-8", errors="ignore")
    for token in ("KEEP", "ADAPT", "BAN", "DEFER"):
        assert token in text, f"classification token {token} missing"
    assert text.count("github.com/") >= 5, "expected several rescanned repo URLs"
