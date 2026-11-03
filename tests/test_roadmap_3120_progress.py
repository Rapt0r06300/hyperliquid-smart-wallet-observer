"""Regression contract for the single 3,120-task Alina Codex roadmap."""
from __future__ import annotations

from pathlib import Path

from tools.roadmap_722_progress import (
    DEFAULT_ROADMAP,
    EXPECTED,
    HVR_APPENDIX,
    INT_INDEX,
    INT_LOTS,
    inspect_roadmap,
)


def _combined() -> str:
    paths = (DEFAULT_ROADMAP, HVR_APPENDIX, INT_INDEX, *INT_LOTS)
    assert len(paths) == 13
    assert all(isinstance(path, Path) and path.is_file() for path in paths)
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_exactly_3120_distinct_identifiers_and_evidence_metadata() -> None:
    assert EXPECTED == {
        "ASF": 150, "AUD": 72, "ECO": 200, "LCH": 300,
        "PNL": 78, "BUG": 300, "HVR": 1000,
        "ASF-HVR-INT": 1000, "ASF-RIG": 20,
    }
    result = inspect_roadmap(_combined())
    assert result["total"] == result["present"] == 3120
    assert result["errors"] == [], result["errors"][:20]
    assert result["verified"] <= result["handled"] <= 3120
    assert sum(v["total"] for v in result["groups"].values()) == 3120
    assert sum(v["verified"] for v in result["groups"].values()) == result["verified"]


def test_historic_and_new_prefixes_do_not_overlap() -> None:
    content = (
        "- [ ] **[ASF-001] Autorité**\n"
        "  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Reçu de clôture :** `PENDING`.\n"
        "- [ ] **[ASF-HVR-INT-0001] Intégration**\n"
        "  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Reçu de clôture :** `PENDING`.\n"
        "- [ ] **[ASF-RIG-001] Rigueur**\n"
        "  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Reçu de clôture :** `PENDING`.\n"
    )
    result = inspect_roadmap(
        content, expected={"ASF": 1, "ASF-HVR-INT": 1, "ASF-RIG": 1}
    )
    assert result["total"] == result["present"] == 3
    assert result["errors"] == [], result["errors"]
    assert all(group["total"] == 1 for group in result["groups"].values())


def test_false_verification_and_duplicate_are_denied() -> None:
    line = (
        "- [x] **[ASF-001] Faussément terminée**\n"
        "  - **Suivi Codex :** `VERIFIED_DONE` · **Priorité :** `P0` · **Reçu de clôture :** `PENDING`.\n"
    )
    result = inspect_roadmap(line + line, expected={"ASF": 1})
    assert any(issue.startswith("DUPLICATE_ID:ASF-001") for issue in result["errors"])
    assert any(issue.startswith("INVALID_VERIFIED_RECEIPT:ASF-001") for issue in result["errors"])


def test_one_file_export_is_complete(tmp_path: Path) -> None:
    import subprocess
    import sys

    target = tmp_path / "ALINA_ROADMAP_3120.md"
    result = subprocess.run(
        [sys.executable, str(DEFAULT_ROADMAP.parents[3] / "tools" / "roadmap_722_progress.py"),
         "--export-md", str(target)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    merged = target.read_text(encoding="utf-8")
    assert "ASF-001" in merged and "HVR-1000" in merged
    assert "ASF-HVR-INT-1000" in merged and "ASF-RIG-020" in merged
    assert len(merged) > 100_000
