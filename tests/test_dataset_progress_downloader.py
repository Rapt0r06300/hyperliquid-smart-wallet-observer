from __future__ import annotations

from hl_observer.datasets.progress_downloader import human_bytes, human_eta


def test_human_bytes_reste_lisible() -> None:
    assert human_bytes(0) == "0.00 B"
    assert human_bytes(1024) == "1.00 KiB"
    assert human_bytes(1024 * 1024) == "1.00 MiB"
    assert human_bytes(1024 * 1024 * 1024) == "1.00 GiB"


def test_human_eta_reste_lisible() -> None:
    assert human_eta(None) == "--:--:--"
    assert human_eta(0) == "00:00:00"
    assert human_eta(65) == "00:01:05"
    assert human_eta(3661) == "01:01:01"
