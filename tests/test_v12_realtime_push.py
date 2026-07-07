from hl_observer.storage.event_log import EventLog
from hl_observer.ui.sse_events import stream_since, format_sse
from hl_observer.ui.authoritative_snapshot import build_authoritative_snapshot
from hl_observer.ui.stale_policy import is_stale, paper_blocked
from hl_observer.ui.full_refresh_fallback import needs_full_refresh
from hl_observer.storage.runtime_state import RuntimeState


def test_event_log_revision_and_replay_missed():
    log = EventLog()
    r1 = log.append(kind="fill", payload={"coin": "BTC"}, ts_ms=1)
    r2 = log.append(kind="fill", payload={"coin": "ETH"}, ts_ms=2)
    assert r1 == 1 and r2 == 2 and log.latest_revision == 2
    missed = log.since(1)                       # client saw rev 1, replay the rest
    assert [e.revision for e in missed] == [2]


def test_sse_frame_carries_revision_as_id():
    log = EventLog()
    log.append(kind="tick", payload={"x": 1}, ts_ms=1)
    frames = stream_since(log, 0)
    assert len(frames) == 1 and frames[0].startswith("id: 1\n") and "event: tick" in frames[0]


def test_authoritative_snapshot_has_revision_and_checksum():
    snap = build_authoritative_snapshot({"a": 1}, revision=7, now_ms=10)
    assert snap["authoritative"] is True and snap["revision"] == 7 and len(snap["checksum"]) == 16
    # deterministic checksum
    assert snap["checksum"] == build_authoritative_snapshot({"a": 1}, revision=7)["checksum"]


def test_stale_policy_blocks_paper():
    assert is_stale(None, 1000) is True
    assert is_stale(1000, 1000 + 20_000, max_age_ms=15_000) is True
    assert is_stale(1000, 1000 + 5_000, max_age_ms=15_000) is False
    assert paper_blocked(last_update_ms=1000, now_ms=1100, refreshing=True) is True   # blocked during refresh
    assert paper_blocked(last_update_ms=1000, now_ms=1100, refreshing=False) is False


def test_full_refresh_when_gap_too_big_or_unknown():
    assert needs_full_refresh(None, 50) is True
    assert needs_full_refresh(10, 200, max_gap=100) is True
    assert needs_full_refresh(190, 200, max_gap=100) is False


def test_runtime_state_persist(tmp_path):
    st = RuntimeState(str(tmp_path / "rt.json"))
    st.set("phase", "scanning")
    assert RuntimeState(str(tmp_path / "rt.json")).get("phase") == "scanning"
