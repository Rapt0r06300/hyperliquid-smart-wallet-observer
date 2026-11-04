"""Flux userFills LIVE → snapshots frais : cœur PUR testé sans réseau.

On verrouille notamment la comptabilité du prix d'entrée et la séparation entre
horloge exchange et réception locale WS, deux invariants indispensables aux
preuves de latence et de replay causal.
"""
from __future__ import annotations

import asyncio
import pytest

import hl_observer.wallets.user_fills_live as live
from hl_observer.config.loader import load_settings
from hl_observer.collection import userfills_live as UL


def test_appliquer_fill_agrege_open_add_avec_prix_moyen_pondere():
    pos = {}
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 20.0, "sz": 10.0, "signe": 1})
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 21.0, "sz": 5.0, "signe": 1})
    assert pos["HYPE"]["szi"] == 15.0
    assert pos["HYPE"]["entryPx"] == pytest.approx((10 * 20 + 5 * 21) / 15)

    entry = pos["HYPE"]["entryPx"]
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 19.0, "sz": 6.0, "signe": -1})
    assert pos["HYPE"]["szi"] == 9.0
    assert pos["HYPE"]["entryPx"] == pytest.approx(entry)

    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 18.0, "sz": 9.0, "signe": -1})
    assert pos["HYPE"]["szi"] == 0.0


def test_appliquer_fill_flip_reinitialise_entree_sur_le_reliquat_oppose():
    pos = {"BTC": {"szi": 10.0, "entryPx": 20.0}}
    UL.appliquer_fill(pos, {"coin": "BTC", "px": 19.0, "sz": 15.0, "signe": -1})
    assert pos["BTC"]["szi"] == -5.0
    assert pos["BTC"]["entryPx"] == 19.0


def test_identite_instrument_native_est_preservee_dans_etat_snapshot_et_fill():
    positions = UL.positions_depuis_snapshot({
        "positions": [{"coin": " kPEPE ", "szi": "2", "entryPx": "0.01"}]
    })
    assert list(positions) == ["kPEPE"]

    UL.appliquer_fill(
        positions, {"coin": "kPEPE", "px": 0.02, "sz": 1, "signe": 1}
    )
    assert set(positions) == {"kPEPE"}


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"positions": [{"coin": "BTC", "entryPx": 100.0}]},
        {"positions": [{"coin": "BTC", "szi": 1.0, "entryPx": float("nan")}]},
        {"positions": [{"coin": "BTC", "szi": 1.0, "entryPx": 100.0},
                        {"coin": " BTC ", "szi": 2.0, "entryPx": 101.0}]},
    ],
)
def test_positions_snapshot_rejette_absence_non_fini_et_doublon(snapshot):
    with pytest.raises(ValueError):
        UL.positions_depuis_snapshot(snapshot)


def test_appliquer_fill_ne_convertit_pas_un_etat_existant_incomplet_en_zero():
    positions = {"BTC": {"szi": 2.0}}
    before = {coin: dict(state) for coin, state in positions.items()}

    UL.appliquer_fill(positions, {"coin": "BTC", "px": 101.0, "sz": 1.0, "signe": 1})

    assert positions == before


def test_appliquer_fill_short_add_est_aussi_pondere():
    pos = {"ETH": {"szi": -4.0, "entryPx": 100.0}}
    UL.appliquer_fill(pos, {"coin": "ETH", "px": 90.0, "sz": 6.0, "signe": -1})
    assert pos["ETH"]["szi"] == -10.0
    assert pos["ETH"]["entryPx"] == pytest.approx((4 * 100 + 6 * 90) / 10)


def test_snapshot_depuis_positions_format():
    pos = {"HYPE": {"szi": 15.0, "entryPx": 21.0}, "VIDE": {"szi": 0.0, "entryPx": 1.0}}
    snap = UL.snapshot_depuis_positions("0xA", pos, nav_usd=100_000, ts_ms=1234)
    assert snap["vault"] == "0xA" and snap["source"] == "userfills_live" and snap["real_execution"] is False
    coins = {p["coin"] for p in snap["positions"]}
    assert coins == {"HYPE"} and snap["n_positions"] == 1


@pytest.mark.parametrize(
    ("vault", "positions", "nav_usd", "ts_ms"),
    [
        ("", {"BTC": {"szi": 1.0, "entryPx": 100.0}}, 100.0, 1),
        ("0xA", {"BTC": {"szi": 1.0, "entryPx": 100.0}}, float("nan"), 1),
        ("0xA", {"BTC": {"szi": 1.0, "entryPx": 100.0}}, 100.0, 0),
        ("0xA", {"BTC": {"szi": 1.0, "entryPx": float("nan")}}, 100.0, 1),
        ("0xA", {"BTC": {"szi": True, "entryPx": 100.0}}, 100.0, 1),
    ],
)
def test_snapshot_depuis_positions_refuse_les_preuves_non_finis(vault, positions, nav_usd, ts_ms):
    with pytest.raises(ValueError):
        UL.snapshot_depuis_positions(vault, positions, nav_usd=nav_usd, ts_ms=ts_ms)


def test_parser_message_userfills_separe_exchange_et_reception_ws():
    msg = {"channel": "userFills", "sequence": 42, "data": {"user": "0xA", "fills": [
        {"coin": "SOL", "px": "150", "sz": "10", "side": "B", "dir": "Open Long", "time": 1000,
         "tid": 7, "oid": 11, "hash": "0xabc"},
        {"bad": 1}]}}
    fills = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1500)
    assert len(fills) == 1
    fill = fills[0]
    assert fill["coin"] == "SOL" and fill["signe"] == 1
    assert fill["ts_ms"] == 1000
    assert fill["received_at_ms"] == 1500
    assert fill["received_at_ms"] - fill["ts_ms"] == 500
    assert fill["tid"] == 7 and fill["oid"] == 11
    assert fill["frame_sequence"] == 42
    assert fill["isSnapshot"] is None
    assert fill["is_snapshot"] is None


@pytest.mark.parametrize("sequence", [True, 1.5, -1, "1.5", "-1"])
def test_parser_ne_tronque_pas_une_sequence_non_entier(sequence):
    msg = {"channel": "userFills", "sequence": sequence, "data": {"fills": [
        {"coin": "SOL", "px": "150", "sz": "1", "side": "B", "time": 1000,
         "tid": 7, "hash": "0xabc"}
    ]}}

    [fill] = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1500)

    assert fill["frame_sequence"] is None


def test_parser_userfills_preserve_la_casse_native_de_l_instrument():
    msg = {"channel": "userFills", "data": {"fills": [
        {"coin": "kPEPE", "px": "0.01", "sz": "1", "side": "B", "time": 1000, "tid": 5}
    ]}}

    [fill] = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1500)

    assert fill["coin"] == "kPEPE"


def test_parser_preserves_unknown_snapshot_classification():
    msg = {"channel": "userFills", "data": {"user": "0xA", "fills": [
        {"coin": "SOL", "px": "150", "sz": "1", "side": "B", "time": 1000, "tid": 6}
    ]}}
    [fill] = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1500)
    assert fill["isSnapshot"] is None
    assert fill["is_snapshot"] is None
    assert UL.liquidations_confirmees([{
        **fill,
        "liquidation": {"liquidatedUser": "0xB"},
    }])[0]["is_snapshot"] is None


@pytest.mark.parametrize("received_at_ms", [None, "invalid", 0, -1])
def test_parser_never_invents_a_receive_timestamp(received_at_ms):
    msg = {"channel": "userFills", "data": {"fills": [
        {"coin": "SOL", "px": "150", "sz": "1", "side": "B", "time": 1000, "tid": 7}
    ]}}
    kwargs = {} if received_at_ms is None else {"received_at_ms": received_at_ms}

    [fill] = UL.parser_message_userfills(msg, vault="0xA", **kwargs)

    assert fill["ts_ms"] == 1000
    assert fill["received_at_ms"] is None


def test_stable_event_id_ne_depend_pas_du_moment_de_reception():
    msg = {"channel": "userFills", "data": {"fills": [
        {"coin": "SOL", "px": "150", "sz": "1", "side": "B", "dir": "Open Long", "time": 1000,
         "tid": 7, "oid": 11, "hash": "0xabc"}
    ]}}
    a = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1200)[0]
    b = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1800)[0]
    assert a["stable_event_id"] == b["stable_event_id"]
    assert a["received_at_ms"] != b["received_at_ms"]


@pytest.mark.parametrize(
    "changes",
    [
        {"hash": None, "tid": None},
        {"time": True},
        {"px": "0"},
        {"sz": "-1"},
        {"side": "?"},
        {"coin": " "},
    ],
)
def test_parser_rejects_fill_missing_native_identity_or_causal_fields(changes):
    fill = {
        "coin": "BTC", "px": "100", "sz": "1", "side": "B",
        "time": 1_000, "hash": "0xfill", "tid": 1,
        **changes,
    }
    message = {"channel": "userFills", "data": {"fills": [fill]}}

    assert UL.parser_message_userfills(
        message, vault="0xA", received_at_ms=1_010
    ) == []


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("startPosition", "NaN", "FILL_START_POSITION_INVALID"),
        ("startPosition", float("inf"), "FILL_START_POSITION_INVALID"),
        ("startPosition", None, "FILL_START_POSITION_INVALID"),
        ("px", True, "FILL_EXECUTION_VALUE_INVALID"),
        ("time", 1_000.5, "FILL_CAUSAL_TIMESTAMP_INVALID"),
    ],
)
def test_parser_rejette_champs_malformes_et_conserve_le_diagnostic_brut(field, value, reason):
    fill = {
        "coin": "SOL", "px": "150", "sz": "1", "side": "B",
        "time": 1_000, "tid": 7, "hash": "0xf", field: value,
    }
    audit = {}

    parsed = UL.parser_message_userfills(
        {"channel": "userFills", "sequence": 42, "data": {"fills": [fill]}},
        vault="0xA", received_at_ms=1_010, connection_id="sock-1", audit=audit,
    )

    assert parsed == []
    assert audit["input_count"] == 1
    assert audit["rejected_by_reason"] == {reason: 1}
    sample = audit["rejected_samples"][0]
    assert sample["index"] == 0
    assert sample["connection_id"] == "sock-1"
    expected_raw = {"type": "float", "repr": "inf"} if value == float("inf") else value
    assert sample["raw_payload"][field] == expected_raw


def test_parser_audit_malformed_rows_without_dropping_other_valid_fills():
    good = {
        "coin": "SOL", "px": "150", "sz": "1", "side": "B",
        "time": 1_000, "tid": 7, "hash": "0xf",
    }
    audit = {}

    parsed = UL.parser_message_userfills(
        {"channel": "userFills", "data": {"fills": [good, "not-a-fill"]}},
        vault="0xA", received_at_ms=1_010, audit=audit,
    )

    assert len(parsed) == 1 and parsed[0]["tid"] == 7
    assert audit["input_count"] == 2
    assert audit["accepted_count"] == 1
    assert audit["rejected_by_reason"] == {"FILL_ROW_NOT_OBJECT": 1}


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("time", float("inf"), "FILL_CAUSAL_TIMESTAMP_INVALID"),
        ("px", float("nan"), "FILL_EXECUTION_VALUE_INVALID"),
        ("sz", float("inf"), "FILL_EXECUTION_VALUE_INVALID"),
    ],
)
def test_parser_isole_une_ligne_non_finie_et_preserve_les_fills_valides(field, value, reason):
    good = {
        "coin": "SOL", "px": "150", "sz": "1", "side": "B",
        "time": 1_000, "tid": 7, "hash": "0xf",
    }
    bad = {**good, "tid": 8, "hash": "0xbad", field: value}
    audit = {}

    parsed = UL.parser_message_userfills(
        {"channel": "userFills", "sequence": 42, "data": {"fills": [good, bad]}},
        vault="0xA", received_at_ms=1_010, audit=audit,
    )

    assert [row["tid"] for row in parsed] == [7]
    assert audit["accepted_count"] == 1
    assert audit["rejected_count"] == 1
    assert audit["rejected_by_reason"] == {reason: 1}
    assert audit["rejected_samples"][0]["raw_payload"][field] == {
        "type": "float", "repr": repr(value),
    }


@pytest.mark.parametrize("field,value", [
    ("px", float("nan")), ("px", float("inf")), ("px", 0.0),
    ("sz", float("nan")), ("sz", float("inf")), ("sz", -1.0),
])
def test_appliquer_fill_invalide_ne_mutate_pas_les_positions_existantes(field, value):
    positions = {"BTC": {"szi": 2.0, "entryPx": 100.0}}
    before = {coin: dict(state) for coin, state in positions.items()}

    UL.appliquer_fill(positions, {
        "coin": "BTC", "px": 101.0, "sz": 1.0, "signe": 1, field: value,
    })

    assert positions == before


def test_fill_websocket_invalide_ne_mutate_pas_une_position_existante():
    positions = {"SOL": {"szi": 2.0, "entryPx": 150.0}}
    before = {coin: dict(state) for coin, state in positions.items()}
    audit = {}
    message = {
        "channel": "userFills",
        "data": {"fills": [{
            "coin": "SOL", "px": "NaN", "sz": "1", "side": "B",
            "time": 1_000, "tid": 7, "hash": "0xf",
        }]},
    }

    fills = UL.parser_message_userfills(
        message, vault="0xA", received_at_ms=1_010, audit=audit,
    )
    for fill in fills:
        UL.appliquer_fill(positions, fill)

    assert fills == []
    assert audit["rejected_by_reason"] == {"FILL_EXECUTION_VALUE_INVALID": 1}
    assert positions == before


def test_store_failure_retries_same_batch_before_abandoning():
    calls = []
    sleeps = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def commit(self):
            return None

    def session_factory():
        return Session()

    original = live.store_user_fills_live_result

    def flaky_store(_session, result, **_kwargs):
        calls.append(result)
        if len(calls) == 1:
            raise OSError("temporary database failure")
        result.fills_stored = 1
        result.deltas_stored = 1
        return result

    async def fake_sleep(delay):
        sleeps.append(delay)

    live.store_user_fills_live_result = flaky_store
    try:
        stats = live.StreamStats()
        ok = asyncio.run(live._store_fresh_fills(
            session_factory, "0x" + "a" * 40, [{"tid": 1}],
            max_live_fill_age_ms=20_000, stats=stats, sleep=fake_sleep,
        ))
    finally:
        live.store_user_fills_live_result = original

    assert ok is True
    assert len(calls) == 2
    assert sleeps == [pytest.approx(0.25)]
    assert stats.storage_failures == 0
    assert stats.fresh_fills_stored == 1


def test_brief_connections_keep_increasing_jittered_backoff():
    class BriefWs:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def send(self, _payload):
            return None

        async def recv(self):
            raise ConnectionError("closed immediately")

    sleeps = []

    def websocket_connect(_url):
        return BriefWs()

    async def fake_sleep(delay):
        sleeps.append(delay)

    stats = asyncio.run(live.stream_user_fills_ws(
        load_settings(),
        wallets=["0x" + "a" * 40],
        session_factory=lambda: None,
        network_read=True,
        websocket_connect=websocket_connect,
        max_reconnects=2,
        backoff_schedule_s=(1, 2, 4),
        sleep=fake_sleep,
    ))

    assert stats.stopped_reason == "max_reconnects"
    assert stats.reconnects == 3
    assert len(sleeps) == 2
    assert 0.8 <= sleeps[0] <= 1.2
    assert 1.6 <= sleeps[1] <= 2.4
    assert sleeps[1] > sleeps[0]
