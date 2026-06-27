"""Phase 13: clean-archive hygiene excludes runtime/data/logs/SQLite/caches and
forbids root archives."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from hyper_smart_observer.audit.archive_audit import audit_archive_readiness, audit_zip_contents


def test_clean_root_ok_then_root_archive_rejected(tmp_path):
    (tmp_path / "hyper_smart_observer").mkdir()
    (tmp_path / "hyper_smart_observer" / "a.py").write_text("x = 1\n", encoding="utf-8")
    ok, _ = audit_archive_readiness(tmp_path)
    assert ok is True
    (tmp_path / "stray.zip").write_bytes(b"PK\x03\x04")  # forbidden root archive
    ok2, msg2 = audit_archive_readiness(tmp_path)
    assert ok2 is False and "root" in msg2.lower()


def test_zip_contents_flag_runtime_and_db_entries(tmp_path):
    dirty = tmp_path / "dirty.zip"
    with ZipFile(dirty, "w") as z:
        z.writestr("src/a.py", "ok")
        z.writestr("logs/run.log", "secret")
        z.writestr("data/state.sqlite3", "db")
        z.writestr("__pycache__/x.pyc", "bytecode")
    clean_ok, forbidden = audit_zip_contents(dirty)
    assert clean_ok is False
    assert any("logs/" in f for f in forbidden)
    assert any(f.endswith(".sqlite3") for f in forbidden)

    clean = tmp_path / "clean.zip"
    with ZipFile(clean, "w") as z:
        z.writestr("src/a.py", "ok")
        z.writestr("docs/README.md", "doc")
    ok, empty = audit_zip_contents(clean)
    assert ok is True and empty == []
