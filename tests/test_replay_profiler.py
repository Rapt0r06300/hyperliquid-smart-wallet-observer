from __future__ import annotations

import pytest

from hl_observer.backtesting.replay_profiler import profile_replay_events


def test_profile_prouve_la_conservation_et_un_digest_deterministe():
    ticks = iter((10.0, 10.125))
    result = profile_replay_events(
        (row for row in (
            {"event_id": "b", "ts_ms": 2_000},
            {"event_id": "a", "ts_ms": 1_000},
        )),
        delay_seconds=0.25,
        clock=lambda: next(ticks),
    )

    assert result["status"] == "VERIFIED"
    assert result["input_events"] == result["output_events"] == 2
    assert result["elapsed_ms"] == pytest.approx(125.0)
    assert result["count_preserved"] is True
    assert result["event_id_multiset_preserved"] is True
    assert result["exactness_preserved"] is True
    assert len(result["output_sha256"]) == 64


def test_profile_reste_invariant_a_lordre_d_entree():
    events = [
        {"event_id": "a", "ts_ms": 1_000},
        {"event_id": "b", "ts_ms": 2_000},
    ]
    first = profile_replay_events(events, delay_seconds=0, clock=lambda: 1.0)
    second = profile_replay_events(reversed(events), delay_seconds=0, clock=lambda: 1.0)

    assert first["output_sha256"] == second["output_sha256"]
    assert first["exactness_preserved"] is second["exactness_preserved"] is True


def test_profile_refuse_une_duree_negative():
    ticks = iter((2.0, 1.0))
    with pytest.raises(ValueError, match="backwards"):
        profile_replay_events(
            [{"event_id": "a", "ts_ms": 1_000}],
            delay_seconds=0,
            clock=lambda: next(ticks),
        )
