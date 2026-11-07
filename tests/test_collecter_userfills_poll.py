"""Orchestration du collecteur poll-forward (sans réseau, poster factice).

Vérifie que la boucle applique la discipline causale : 1re passe = amorçage
(aucun causal), passes suivantes = seuls les nouveaux fills, tagués LIVE_POLL
avec observed_at = instant du poll, et que le high-water persiste.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.collecter_userfills_poll import (
    OUT_FILLS,
    POLL_SOURCE_ID,
    STATE_PATH,
    _load_state,
    _save_state,
    poll_once,
)


def _fill(time_ms: int, tid: int) -> dict:
    return {"time": time_ms, "tid": tid, "coin": "BTC", "px": 100.0, "sz": 1.0, "side": "B",
            "fee": "0.01", "startPosition": "0", "closedPnl": "0", "dir": "Open Long"}


def test_bootstrap_then_only_new_fills_are_causal(tmp_path: Path) -> None:
    calls = {"n": 0}

    def poster(_vault: str, _start: int, _end: int):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_fill(1_000, 1), _fill(2_000, 2)]      # préexistants
        return [_fill(2_000, 2), _fill(3_000, 9)]          # 9 est nouveau

    state: dict = {}
    n1 = poll_once(tmp_path, ["0xLEAD"], state, poster=poster, now_ms=5_000)
    assert n1 == 0                                         # amorçage : rien de causal
    assert state["0xLEAD"].high_water_ms == 2_000

    n2 = poll_once(tmp_path, ["0xLEAD"], state, poster=poster, now_ms=8_000)
    assert n2 == 1                                         # seul tid 9

    lines = (tmp_path / OUT_FILLS).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["source"] == "LIVE_POLL"
    assert row["source_id"] == POLL_SOURCE_ID
    assert row["isSnapshot"] is False
    assert row["observed_at_ms"] == 8_000                  # instant du poll
    assert row["tid"] == 9
    assert row["vault"] == "0xLEAD"


def test_watermark_persists_across_restarts(tmp_path: Path) -> None:
    def poster(_v, _s, _e):
        return [_fill(4_000, 4)]

    state: dict = {}
    poll_once(tmp_path, ["0xV"], state, poster=poster, now_ms=10_000)  # bootstrap -> hw 4000
    _save_state(tmp_path / STATE_PATH, state)

    reloaded = _load_state(tmp_path / STATE_PATH)
    assert reloaded["0xV"].initialised is True
    assert reloaded["0xV"].high_water_ms == 4_000

    # Après redémarrage, un fill <= high-water ne redevient pas causal.
    n = poll_once(tmp_path, ["0xV"], reloaded, poster=lambda *_: [_fill(4_000, 4)], now_ms=11_000)
    assert n == 0


def test_network_error_is_fail_soft(tmp_path: Path) -> None:
    def poster(*_a):
        raise TimeoutError("réseau")

    state: dict = {}
    n = poll_once(tmp_path, ["0xV"], state, poster=poster, now_ms=10_000)
    assert n == 0  # pas de crash, pas de fill


def test_pagination_captures_all_fills_beyond_the_response_cap(tmp_path: Path) -> None:
    # Solution #1 : si une page atteint le cap, on pagine jusqu'à tout capturer.
    from hl_observer.collection.forward_poll_fills import RESPONSE_PAGE_CAP

    page1 = [_fill(1_000 + i, 1_000 + i) for i in range(RESPONSE_PAGE_CAP)]  # page pleine
    page2 = [_fill(9_000, 9_999)]                                           # reliquat
    calls = {"n": 0}

    def poster(_v, start, _end):
        calls["n"] += 1
        return page1 if calls["n"] == 1 else page2

    state: dict = {}
    # 1re passe = amorçage : fixe le high-water sur TOUT (pagination incluse).
    poll_once(tmp_path, ["0xV"], state, poster=poster, now_ms=20_000)
    assert calls["n"] >= 2                      # a bien paginé
    assert state["0xV"].high_water_ms == 9_000  # a vu le fill au-delà du cap
