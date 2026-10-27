from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_portable_readme_is_machine_agnostic_and_describes_a_clone() -> None:
    text = (ROOT / "docs" / "portfolio" / "PORTABLE_README.txt").read_text(encoding="utf-8-sig")
    lower = text.lower()

    assert "clone fonctionne depuis son propre chemin local" in lower
    assert "lancer_hypersmart.cmd" in lower
    assert "alina_sync_complete.cmd" in lower
    assert "aucune archive portable séparée" in lower
    assert "c:\\" not in lower
    assert "c:/" not in lower
    assert "\\users\\" not in lower
