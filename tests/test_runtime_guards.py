"""Tests résilience runtime."""
from __future__ import annotations

import os

from hl_observer.backtesting.runtime_guards import (
    EventBus,
    heartbeat_stale,
    parent_alive,
    rotate_logs,
    source_health,
)


def test_parent_alive():
    assert parent_alive(os.getpid()) is True      # nous-mêmes : vivants
    assert parent_alive(-1) is False
    assert parent_alive("pas_un_pid") is False


def test_heartbeat_stale():
    assert heartbeat_stale(100.0, 700.0, threshold=600.0) is False   # pile au seuil
    assert heartbeat_stale(100.0, 800.0, threshold=600.0) is True    # gelé


def test_rotate_logs_archives_big_file(tmp_path):
    p = tmp_path / "big.log"
    p.write_text("x" * 5000)
    archived = rotate_logs(str(tmp_path), max_bytes=1000, keep=5)
    assert len(archived) == 1
    assert os.path.getsize(str(p)) == 0                  # recréé vide
    assert os.path.exists(archived[0])                   # archivé, pas supprimé


def test_source_health():
    h = source_health({"ws": 100.0, "funding": 10.0}, now=120.0, max_age=30.0)
    assert h["ws"] == "OK" and h["funding"] == "STALE"


def test_event_bus_delivers():
    bus = EventBus()
    got = []
    bus.subscribe("fill", got.append)
    bus.subscribe("fill", got.append)
    assert bus.publish("fill", {"coin": "BTC"}) == 2
    assert len(got) == 2


def test_parent_alive_survit_a_un_pid_absurde():
    """Fuzzing de l'audit : un PID enorme faisait lever OverflowError -> le WATCHDOG crashait,
    donc plus personne ne surveillait la mort du parent. Le garde-fou doit etre incassable."""
    from hl_observer.backtesting.runtime_guards import parent_alive
    for absurde in (int(1e18), -1, 2**40, "abc", None):
        assert parent_alive(absurde) is False
