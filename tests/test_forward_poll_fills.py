"""Preuve de rigueur du poll-forward causal (casser le cap WS sans tricher).

Le point critique : un fill n'est JAMAIS causal s'il a pu être connu autrement
qu'en l'observant se former vers l'avant. On prouve ici :
- 1re observation d'un leader -> aucun fill causal (préexistants = snapshot) ;
- seuls les fills strictement nouveaux des passes suivantes sont causaux ;
- un fill vu à la 1re passe ne redevient jamais causal plus tard ;
- observed_at est l'instant réel du poll (pas l'heure d'échange) ;
- fail-closed sans horloge/identité ;
- la source LIVE_POLL est traitée comme causale, le backfill non.
"""
from __future__ import annotations

from hl_observer.collection.forward_poll_fills import (
    LIVE_POLL_SOURCE,
    LeaderCooldown,
    LeaderWatermark,
    TokenBucket,
    adaptive_interval_s,
    collector_stream_health,
    is_causal_live_source,
    merge_dedup_fills,
    partition_forward_fills,
    prioritize_leaders,
    shard_leaders,
)


def _fill(time_ms: int, tid: int, coin: str = "BTC", px: float = 100.0) -> dict:
    return {"time": time_ms, "tid": tid, "coin": coin, "px": px, "sz": 1.0, "side": "B"}


def test_first_observation_emits_no_causal_fill() -> None:
    wm = LeaderWatermark()  # jamais observé
    fills = [_fill(1_000, 1), _fill(2_000, 2), _fill(1_500, 3)]
    causal, new_wm = partition_forward_fills(wm, fills, observed_at_ms=5_000)
    assert causal == []  # préexistants -> snapshot, exclus
    assert new_wm.initialised is True
    assert new_wm.high_water_ms == 2_000
    assert new_wm.high_water_ids == {"tid:2"}


def test_second_poll_emits_only_new_fills_as_causal() -> None:
    _, wm = partition_forward_fills(LeaderWatermark(), [_fill(1_000, 1), _fill(2_000, 2)], observed_at_ms=5_000)
    # Nouvelle passe : un fill déjà vu (2_000/tid2) + un nouveau (3_000/tid9).
    causal, new_wm = partition_forward_fills(wm, [_fill(2_000, 2), _fill(3_000, 9)], observed_at_ms=8_000)
    assert [f["tid"] for f in causal] == [9]
    row = causal[0]
    assert row["source"] == LIVE_POLL_SOURCE
    assert row["isSnapshot"] is False
    assert row["observed_at_ms"] == 8_000  # instant réel du poll, pas time=3_000
    assert row["observation_transport"] == "hyperliquid_rest_poll"
    assert new_wm.high_water_ms == 3_000


def test_a_fill_from_the_first_poll_never_becomes_causal() -> None:
    # Invariant anti-look-ahead : un fill préexistant réapparaissant plus tard
    # ne doit jamais être émis comme causal.
    _, wm = partition_forward_fills(LeaderWatermark(), [_fill(1_000, 1), _fill(2_000, 2)], observed_at_ms=5_000)
    causal, _ = partition_forward_fills(wm, [_fill(1_000, 1), _fill(2_000, 2)], observed_at_ms=9_000)
    assert causal == []


def test_same_ms_new_identity_is_causal_but_seen_identity_is_not() -> None:
    _, wm = partition_forward_fills(LeaderWatermark(), [_fill(2_000, 2)], observed_at_ms=5_000)
    # Même ms que le high-water : tid 2 déjà vu (exclu), tid 7 inédit (causal).
    causal, new_wm = partition_forward_fills(wm, [_fill(2_000, 2), _fill(2_000, 7)], observed_at_ms=6_000)
    assert [f["tid"] for f in causal] == [7]
    assert new_wm.high_water_ms == 2_000
    assert new_wm.high_water_ids == {"tid:2", "tid:7"}


def test_fills_older_than_high_water_are_never_causal() -> None:
    _, wm = partition_forward_fills(LeaderWatermark(), [_fill(5_000, 5)], observed_at_ms=10_000)
    causal, _ = partition_forward_fills(wm, [_fill(3_000, 3), _fill(4_000, 4)], observed_at_ms=11_000)
    assert causal == []


def test_fail_closed_without_clock_or_identity() -> None:
    _, wm = partition_forward_fills(LeaderWatermark(), [_fill(1_000, 1)], observed_at_ms=5_000)
    bad = [
        {"tid": 10, "coin": "BTC"},             # pas de time
        {"time": 9_000, "coin": "BTC"},         # pas de tid/hash
        {"time": 0, "tid": 11},                 # time invalide
    ]
    causal, new_wm = partition_forward_fills(wm, bad, observed_at_ms=12_000)
    assert causal == []
    assert new_wm.high_water_ms == 1_000  # inchangé


def test_hash_identity_is_supported() -> None:
    _, wm = partition_forward_fills(LeaderWatermark(), [{"time": 1_000, "hash": "a" * 10}], observed_at_ms=5_000)
    causal, _ = partition_forward_fills(wm, [{"time": 2_000, "hash": "b" * 10}], observed_at_ms=6_000)
    assert len(causal) == 1 and causal[0]["hash"] == "b" * 10


def test_watermark_state_round_trips() -> None:
    _, wm = partition_forward_fills(LeaderWatermark(), [_fill(2_000, 2), _fill(2_000, 3)], observed_at_ms=5_000)
    restored = LeaderWatermark.from_state(wm.to_state())
    assert restored.initialised is True
    assert restored.high_water_ms == 2_000
    assert restored.high_water_ids == {"tid:2", "tid:3"}
    # Et il continue de filtrer correctement après restauration.
    causal, _ = partition_forward_fills(restored, [_fill(2_000, 2), _fill(2_500, 8)], observed_at_ms=7_000)
    assert [f["tid"] for f in causal] == [8]


def test_invalid_observed_at_is_rejected() -> None:
    import pytest
    with pytest.raises(ValueError):
        partition_forward_fills(LeaderWatermark(initialised=True), [], observed_at_ms=0)


def test_causal_source_helper() -> None:
    assert is_causal_live_source("LIVE_WS") is True
    assert is_causal_live_source(LIVE_POLL_SOURCE) is True
    assert is_causal_live_source("REST_BACKFILL") is False
    assert is_causal_live_source("WS_BOOTSTRAP") is False
    assert is_causal_live_source(None) is False


def test_shard_leaders_are_disjoint_and_cover_everything() -> None:
    leaders = [f"0x{i:02d}" for i in range(10)]
    assert shard_leaders(leaders, 1, 0) == leaders
    s0 = shard_leaders(leaders, 3, 0)
    s1 = shard_leaders(leaders, 3, 1)
    s2 = shard_leaders(leaders, 3, 2)
    assert set(s0) | set(s1) | set(s2) == set(leaders)          # couverture totale
    assert set(s0) & set(s1) == set() and set(s1) & set(s2) == set()  # disjoints
    import pytest
    with pytest.raises(ValueError):
        shard_leaders(leaders, 3, 3)


def test_adaptive_interval_shortens_when_active_and_spaces_when_idle() -> None:
    base = 6.0
    assert adaptive_interval_s(base, 0) > base       # inactif -> espacé
    assert adaptive_interval_s(base, 10) < base      # très actif -> dense
    assert adaptive_interval_s(base, 2) == base      # activité moyenne -> base
    # bornes respectées
    assert adaptive_interval_s(1.0, 100, min_s=2.0, max_s=60.0) == 2.0
    assert adaptive_interval_s(100.0, 0, min_s=2.0, max_s=60.0) == 60.0


def test_token_bucket_allows_burst_then_throttles_to_rate() -> None:
    # #1 : rafale jusqu'à `burst` sans attente, puis ~1/rate entre requêtes.
    clock = {"t": 0.0}
    slept: list[float] = []

    def now():
        return clock["t"]

    def sleep(s):
        slept.append(s)
        clock["t"] += s  # le sommeil fait avancer l'horloge

    tb = TokenBucket(rate_per_s=2.0, burst=3.0, now=now, sleep=sleep)
    assert [tb.take() for _ in range(3)] == [0.0, 0.0, 0.0]  # rafale gratuite
    waited = tb.take()                                       # 4e -> doit attendre
    assert waited > 0.0
    assert abs(waited - 0.5) < 1e-9                          # 1 jeton à 2/s = 0.5 s


def test_prioritize_leaders_puts_retained_first_without_dup() -> None:
    # #2 : les retenus passent devant, ordre stable, pas de doublon (casse insensible).
    leaders = ["0xAAA", "0xBBB", "0xCCC", "0xBBB"]
    out = prioritize_leaders(leaders, retained=["0xccc"])
    assert out == ["0xCCC", "0xAAA", "0xBBB"]


def test_leader_cooldown_backs_off_one_leader_and_spares_others() -> None:
    # #3 : un leader fautif est mis en pause croissante ; les autres restent dus.
    cd = LeaderCooldown(base_ms=1_000.0, max_ms=10_000.0)
    assert cd.due("0xA", now_ms=0.0) is True
    cd.penalize("0xA", now_ms=0.0)
    assert cd.due("0xA", now_ms=500.0) is False   # en pause
    assert cd.due("0xA", now_ms=1_000.0) is True  # pause finie
    assert cd.due("0xB", now_ms=0.0) is True       # un autre leader non affecté
    cd.penalize("0xA", now_ms=1_000.0)             # 2e strike -> 2x plus long
    assert cd.due("0xA", now_ms=2_500.0) is False
    cd.reset("0xA")                                # un succès réarme
    assert cd.due("0xA", now_ms=2_500.0) is True


def test_merge_dedup_prefers_non_snapshot_and_drops_doubles() -> None:
    # #4 : même trade vu par WS (snapshot) et poll (causal) -> 1 ligne causale.
    ws = [{"vault": "0xV", "coin": "BTC", "time": 1_000, "tid": 7, "isSnapshot": True}]
    poll = [{"vault": "0xV", "coin": "BTC", "time": 1_000, "tid": 7, "isSnapshot": False},
            {"vault": "0xV", "coin": "ETH", "time": 2_000, "tid": 8, "isSnapshot": False}]
    merged = merge_dedup_fills(ws, poll)
    assert len(merged) == 2                                   # pas de doublon
    btc = [m for m in merged if m["coin"] == "BTC"][0]
    assert btc["isSnapshot"] is False                         # vue causale préférée


def test_collector_stream_health_verdicts() -> None:
    # #5 : FRESH / STALE / DEAD / ABSENT selon l'âge du dernier écrit.
    now = 1_000_000.0
    assert collector_stream_health(now - 500, now, expected_interval_ms=1_000) == "FRESH"
    assert collector_stream_health(now - 5_000, now, expected_interval_ms=1_000) == "STALE"
    assert collector_stream_health(now - 50_000, now, expected_interval_ms=1_000) == "DEAD"
    assert collector_stream_health(0, now, expected_interval_ms=1_000) == "ABSENT"


def test_poll_causal_fill_keeps_dedup_identity_fields() -> None:
    # Solution #4 : un fill de poll conserve tid/hash/coin/px/sz -> même identité
    # qu'un fill WS du même trade -> fusion/dédup garantie en aval.
    _, wm = partition_forward_fills(LeaderWatermark(), [_fill(1_000, 1)], observed_at_ms=5_000)
    causal, _ = partition_forward_fills(wm, [{"time": 2_000, "tid": 7, "coin": "ETH", "px": 50.0, "sz": 2.0}], observed_at_ms=6_000)
    row = causal[0]
    for field in ("time", "tid", "coin", "px", "sz"):
        assert field in row
