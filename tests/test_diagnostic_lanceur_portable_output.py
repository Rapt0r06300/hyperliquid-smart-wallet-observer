from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_lanceur_writes_only_under_runtime_reports() -> None:
    script = (ROOT / "tools/launchers/DIAGNOSTIC_LANCEUR.cmd").read_text(encoding="utf-8-sig")
    lower = script.lower()

    assert 'set "rapport_dir=%alina_project_root%\\runtime\\reports"' in lower
    assert 'set "rapport=%rapport_dir%\\diagnostic_lanceur.txt"' in lower
    assert 'set "rapport=%alina_project_root%\\diagnostic_lanceur.txt"' not in lower


def test_archived_diagnostic_note_is_portable_pointer_not_machine_dump() -> None:
    note = (ROOT / "docs/archive/root-history/DIAGNOSTIC_LANCEUR.txt").read_text(encoding="utf-8-sig")
    lower = note.lower()

    assert "runtime\\reports\\diagnostic_lanceur.txt" in lower
    assert "c:\\users\\" not in lower
    assert "comspec" not in lower
    assert "python.exe" not in lower
