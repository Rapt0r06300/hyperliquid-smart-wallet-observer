import json

import pytest

from tools import collect_okx_copy_traders as collector


def _phase(epoch: int, phase: str = "COLLECT") -> dict[str, object]:
    started = "2026-10-25T00:00:00Z" if phase != "IDLE" else None
    analyzing = phase == "ANALYZE"
    return {
        "schema_version": 1,
        "phase": phase,
        "epoch": epoch,
        "requested_at_utc": "2026-10-25T00:00:00Z",
        "collection_started_at_utc": started,
        "collection_cutoff_at_utc": "2026-10-25T01:00:00Z" if analyzing else None,
        "source_collection_epoch": epoch if analyzing else None,
        "analysis_stage": "REPLAY" if analyzing else None,
        "requested_by": "test",
        "request_id": None,
    }


def test_phase_guard_stops_when_local_epoch_changes(tmp_path, monkeypatch):
    state_path = tmp_path / "phase.json"
    state_path.write_text(json.dumps(_phase(4)), encoding="utf-8")
    guard = collector.PhaseEpochGuard(expected_epoch=4, path=state_path, url=None)
    monkeypatch.setattr(collector, "PHASE_POLL_INTERVAL_SECONDS", 0)

    assert guard.is_current()
    state_path.write_text(json.dumps(_phase(5)), encoding="utf-8")

    assert not guard.is_current()
    assert guard.reason == "phase=COLLECT epoch=5"


def test_phase_guard_stops_when_phase_leaves_collect(tmp_path, monkeypatch):
    state_path = tmp_path / "phase.json"
    state_path.write_text(json.dumps(_phase(4, "ANALYZE")), encoding="utf-8")
    guard = collector.PhaseEpochGuard(expected_epoch=4, path=state_path, url=None)
    monkeypatch.setattr(collector, "PHASE_POLL_INTERVAL_SECONDS", 0)

    assert not guard.is_current()
    assert guard.reason == "phase=ANALYZE epoch=4"


@pytest.mark.parametrize(
    "url",
    [
        "http://raw.githubusercontent.com/org/repo/main/control/alina-phase.json",
        "https://example.com/org/repo/main/control/alina-phase.json",
        "https://raw.githubusercontent.com/org/repo/other/control/alina-phase.json",
        "https://raw.githubusercontent.com/Rapt0r06300/hyperliquid-smart-wallet-observer/main/control/alina-phase.json?x=1",
    ],
)
def test_phase_state_url_rejects_noncanonical_targets(url):
    with pytest.raises(ValueError):
        collector._read_phase_snapshot(None, url)


def test_phase_state_url_reads_only_canonical_main_snapshot(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(_phase(8)).encode()

    monkeypatch.setattr(collector, "urlopen", lambda _request, timeout: Response())
    state = collector._read_phase_snapshot(
        None,
        "https://raw.githubusercontent.com/Rapt0r06300/hyperliquid-smart-wallet-observer/main/control/alina-phase.json",
    )

    assert state["phase"] == "COLLECT"
    assert state["epoch"] == 8
