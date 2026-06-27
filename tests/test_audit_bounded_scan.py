"""M1 proof: the safety audit walk never traverses data/, logs/, runtime/.

Bounded walk prunes big runtime dirs AT DESCENT and enforces defensive limits
(max_files / max_bytes / deadline) with an explicit stopped_reason.
Read-only, no network, no orders.
"""

from __future__ import annotations

from pathlib import Path

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.audit.bounded_walk import bounded_walk
from hyper_smart_observer.runtime.runtime_check import scan_runtime_files


def _make_tree(root: Path) -> None:
    (root / "hyper_smart_observer").mkdir(parents=True, exist_ok=True)
    (root / "hyper_smart_observer" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    for big in ("data", "logs", "runtime", "__pycache__", ".git"):
        d = root / big
        (d / "sub").mkdir(parents=True, exist_ok=True)
        (d / "huge.bin").write_bytes(b"0" * 16)
        (d / "sub" / "more.bin").write_bytes(b"0" * 16)


def test_bounded_walk_prunes_big_runtime_dirs(tmp_path):
    _make_tree(tmp_path)
    walk = bounded_walk(tmp_path, extra_excluded_dirs={"logs"})
    seen = {p.as_posix() for p in walk.files}
    assert any("hyper_smart_observer/mod.py" in s for s in seen)
    for big in ("/data/", "/logs/", "/runtime/", "/.git/", "/__pycache__/"):
        assert not any(big in s for s in seen), f"traversed excluded dir: {big}"
    pruned_names = {Path(p).name for p in walk.pruned_dirs}
    assert {"data", "logs", "runtime", ".git", "__pycache__"} <= pruned_names


def test_bounded_walk_stops_on_max_files(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    for i in range(50):
        (d / f"f{i}.py").write_text("x\n", encoding="utf-8")
    walk = bounded_walk(tmp_path, max_files=10)
    assert walk.stopped_reason == "max_files"
    assert walk.files_seen == 10


def test_bounded_walk_deadline_is_explicit(tmp_path):
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    walk = bounded_walk(tmp_path, max_seconds=0.0)
    assert walk.stopped_reason == "deadline"


def test_scan_runtime_files_never_traverses_data(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "hidden.sqlite3").write_bytes(b"x")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "legacy.sqlite3").write_bytes(b"x")
    cfg = AppConfig(runtime_root=tmp_path, database_path=tmp_path / "data" / "app.sqlite3")
    report = scan_runtime_files(cfg)
    db_names = {p.name for p in report.databases}
    assert "legacy.sqlite3" in db_names           # logs/ top-level still detected
    assert "hidden.sqlite3" not in db_names        # data/ is NEVER traversed
    assert len(report.logs_databases) == 1
