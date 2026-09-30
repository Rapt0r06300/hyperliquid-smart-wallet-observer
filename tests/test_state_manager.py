from __future__ import annotations

from hl_observer.core.state_manager import StateManager


def test_state_manager_atomic_save_load(tmp_path):
    manager = StateManager(tmp_path / "state.json")
    manager.save({"wallets": 3, "phase": "scan"})

    assert manager.load()["wallets"] == 3
    assert not (tmp_path / "state.json.tmp").exists()


def test_state_manager_snapshot_before_crash(tmp_path):
    manager = StateManager(tmp_path / "crash.json")
    manager.snapshot_before_crash({"open_positions": 2}, reason="test")

    state = manager.load()
    assert state["open_positions"] == 2
    assert state["crash_snapshot"]["reason"] == "test"
    assert state["crash_snapshot"]["simulation_only"] is True
