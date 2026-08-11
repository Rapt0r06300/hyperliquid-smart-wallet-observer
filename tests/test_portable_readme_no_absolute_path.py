from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_portable_readme_is_machine_agnostic_and_points_to_official_builder() -> None:
    text = (ROOT / "PORTABLE_README.txt").read_text(encoding="utf-8-sig")
    lower = text.lower()

    assert "creer_archive_portable.cmd" in lower
    assert "release_ready" in lower
    assert "c:\\" not in lower
    assert "c:/" not in lower
    assert "\\users\\" not in lower
    assert "winrar" in lower
    assert "ne jamais fabriquer" in lower
