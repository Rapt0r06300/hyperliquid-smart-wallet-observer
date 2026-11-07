"""Orchestration du collecteur poll-forward (sans réseau, poster factice).

Vérifie que la boucle applique la discipline causale : 1re passe = amorçage
(aucun causal), passes suivantes = seuls les nouveaux fills, tagués LIVE_POLL
avec observed_at = instant du poll, et que le high-water persiste.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.collection.forward_poll_fills import LeaderCooldown
from tools.collecter_userfills_poll import (
    OUT_FILLS,
    POLL_SOURCE_ID,
    STATE_PATH,
    _ecrire_page_sante,
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


def test_poll_once_skips_leader_in_backoff_and_penalizes_on_error(tmp_path: Path) -> None:
    # #3 : un leader déjà en backoff n'est PAS interrogé ; un leader qui erreur
    # est mis en backoff (les autres continuent).
    appeles: list[str] = []

    def poster(vault, _s, _e):
        appeles.append(vault)
        if vault == "0xBAD":
            raise RuntimeError("boom")
        return [_fill(1_000, 1)]

    cd = LeaderCooldown(base_ms=10_000.0)
    cd.penalize("0xPAUSE", now_ms=0.0)  # déjà en pause
    state: dict = {}
    poll_once(tmp_path, ["0xPAUSE", "0xBAD", "0xOK"], state, poster=poster, now_ms=1_000, cooldown=cd)
    assert "0xPAUSE" not in appeles        # sauté (backoff)
    assert "0xBAD" in appeles and "0xOK" in appeles
    assert cd.due("0xBAD", now_ms=1_000) is False   # pénalisé après erreur
    assert cd.due("0xOK", now_ms=1_000) is True      # succès -> pas de pause


def test_health_page_is_written_with_verdicts(tmp_path: Path) -> None:
    # #5/#10 : la page de santé est produite (HTML + JSON) et classe les flux.
    import json as _json

    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_fills_poll.jsonl").write_text("{}\n", encoding="utf-8")
    now = __import__("time").time() * 1000.0
    _ecrire_page_sante(tmp_path, now, {"leaders": 5, "polles": 3, "fills_emis": 42, "en_backoff": 1})

    page = (tmp_path / "runtime" / "data" / "collecteurs_sante.html").read_text(encoding="utf-8")
    assert "Santé des collecteurs" in page and "42" in page
    snap = _json.loads((tmp_path / "runtime" / "data" / "collecteurs_sante.json").read_text(encoding="utf-8"))
    assert snap["resume_poll"]["fills_emis"] == 42
    poll_stream = [f for f in snap["flux"] if "poll" in f["fichier"]][0]
    assert poll_stream["verdict"] == "FRESH"       # écrit à l'instant


def test_pagination_captures_all_forward_fills_beyond_the_response_cap(tmp_path: Path) -> None:
    # Solution #1 : sur une passe FORWARD, si une page atteint le cap, on pagine
    # jusqu'à tout capturer. (L'amorçage, lui, ne prend qu'une page.)
    from hl_observer.collection.forward_poll_fills import RESPONSE_PAGE_CAP

    full_page = [_fill(2_000 + i, 2_000 + i) for i in range(RESPONSE_PAGE_CAP)]  # pleine
    tail_page = [_fill(90_000, 99_999)]                                         # reliquat
    calls = {"n": 0}

    def poster(_v, _start, _end):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_fill(1_000, 1)]            # amorçage (1 page)
        if calls["n"] == 2:
            return full_page                    # forward, page pleine -> paginer
        return tail_page                        # page suivante

    state: dict = {}
    poll_once(tmp_path, ["0xV"], state, poster=poster, now_ms=20_000)   # amorçage
    assert state["0xV"].high_water_ms == 1_000
    poll_once(tmp_path, ["0xV"], state, poster=poster, now_ms=100_000)  # forward paginé
    assert calls["n"] >= 3                       # amorçage + >=2 pages forward
    assert state["0xV"].high_water_ms == 90_000  # a vu le fill au-delà du cap
