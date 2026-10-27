from __future__ import annotations

from pathlib import Path

from tools.run_bounded_collector import _RotatingLog


def test_bounded_collector_log_rotates_without_losing_recent_chunks(tmp_path: Path) -> None:
    path = tmp_path / "worker.log"

    with _RotatingLog(path, max_bytes=8, backup_count=2) as output:
        output.write(b"oldest!!")
        output.write(b"middle!!")
        output.write(b"newest!!")

    assert path.read_bytes() == b"newest!!"
    assert path.with_name("worker.log.1").read_bytes() == b"middle!!"
    assert path.with_name("worker.log.2").read_bytes() == b"oldest!!"
    assert sum(item.stat().st_size for item in tmp_path.iterdir()) == 24
