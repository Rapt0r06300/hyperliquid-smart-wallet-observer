from pathlib import Path

from hyper_smart_observer.runtime.archive import is_archive_safe_source


def test_archive_safe_source_rejects_symlink(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    candidate = root / "docs" / "external.txt"
    candidate.parent.mkdir()
    candidate.write_text("placeholder", encoding="utf-8")

    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        if path == candidate:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    assert is_archive_safe_source(root, candidate) is False
