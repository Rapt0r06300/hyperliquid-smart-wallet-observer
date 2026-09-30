from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_lanceur_writes_only_under_runtime_reports() -> None:
    script = (ROOT / "DIAGNOSTIC_LANCEUR.cmd").read_text(encoding="utf-8-sig")
    lower = script.lower()

    assert 'set "rapport_dir=%~dp0runtime\\reports"' in lower
    assert 'set "rapport=%rapport_dir%\\diagnostic_lanceur.txt"' in lower
    assert 'set "rapport=%~dp0diagnostic_lanceur.txt"' not in lower


def test_tracked_diagnostic_txt_is_portable_pointer_not_machine_dump() -> None:
    note = (ROOT / "DIAGNOSTIC_LANCEUR.txt").read_text(encoding="utf-8-sig")
    lower = note.lower()

    assert "runtime\\reports\\diagnostic_lanceur.txt" in lower
    assert "c:\\users\\" not in lower
    assert "comspec" not in lower
    assert "python.exe" not in lower
