from __future__ import annotations

import json

import pytest

import hl_observer.experimental.signaux as signaux


def test_event_freshness_positive_timestamp_and_clock_helpers(tmp_path) -> None:
    assert signaux._fraicheur_evenement(None, 1000) == "TS_ABSENT"
    assert signaux._fraicheur_evenement(0, 31_000) == "STALE_SIGNAL"
    assert signaux._fraicheur_evenement(4_000, 1_000) == "CLOCK_SKEW_FUTURE_DATA"
    assert signaux._fraicheur_evenement(900, 1_000) is None

    assert signaux._positif("1.5")
    assert not signaux._positif(0)
    assert not signaux._positif("bad")

    record = {"a": None, "b": True, "c": "bad", "d": "12.5"}
    assert signaux._timestamp_ms(record, "a", "b", "c", "d") == 12.5
    assert signaux._timestamp_ms(record, "a", "b", "c") is None

    missing = signaux._pair_snapshot_clock({}, now_wall_ms=10_000)
    assert missing == (None, None, None, None)
    snapshot = {
        "recv_wall_hl_ms": 9_500,
        "recv_wall_bin_ms": 9_400,
        "write_wall_ts_ms": 9_600,
        "age_hl_ms": 50,
        "age_bin_ms": 75,
    }
    age, desync, observed, stored_age = signaux._pair_snapshot_clock(snapshot, now_wall_ms=10_000)
    assert age == 600.0
    assert desync == 100.0
    assert observed == 9_600.0
    assert stored_age == 75.0


def test_snapshots_bbo_and_allmids_read_only_files(tmp_path) -> None:
    assert signaux._snapshots_bbo(tmp_path) == {}
    bbo_path = tmp_path / signaux.SYNCHRO_RELPATH
    bbo_path.parent.mkdir(parents=True)
    bbo_path.write_text(
        "\n".join(
            [
                "bad json",
                json.dumps({"coin": "btc", "hl_bid": 99, "bin_bid": 100, "event_id": "old"}),
                json.dumps({"coin": "BTC", "hl_bid": 101, "bin_bid": 102, "event_id": "new"}),
                json.dumps({"coin": "ETH", "hl_bid": 1}),
            ]
        ),
        encoding="utf-8",
    )
    rows = signaux._snapshots_bbo(tmp_path)
    assert set(rows) == {"BTC"}
    assert rows["BTC"]["event_id"] == "new"

    assert signaux._allmids(tmp_path, now_ms=10_000) == {}
    mids_path = tmp_path / signaux.ALLMIDS_RELPATH
    mids_path.write_text("{", encoding="utf-8")
    assert signaux._allmids(tmp_path, now_ms=10_000) == {}
    mids_path.write_text(
        json.dumps({"ts_ms": 1_000, "mids": {"btc": "100", "ETH": 0, "BAD": "x"}}),
        encoding="utf-8",
    )
    assert signaux._allmids(tmp_path, now_ms=100_000) == {}
    assert signaux._allmids(tmp_path, now_ms=10_000) == {"BTC": 100.0}


def test_cross_venue_metrics_cover_fresh_stale_and_rank(monkeypatch) -> None:
    snapshots = {
        "BTC": {
            "recv_wall_hl_ms": 9_500,
            "recv_wall_bin_ms": 9_450,
            "write_wall_ts_ms": 9_600,
            "age_hl_ms": 0,
            "age_bin_ms": 0,
            "hl_bid": 101.0,
            "hl_ask": 102.0,
            "bin_bid": 104.0,
            "bin_ask": 105.0,
            "taille_top_usd": 250.0,
        },
        "OLD": {
            "recv_wall_hl_ms": 1_000,
            "recv_wall_bin_ms": 1_000,
            "write_wall_ts_ms": 1_000,
            "hl_bid": 1.0,
            "hl_ask": 2.0,
            "bin_bid": 3.0,
            "bin_ask": 4.0,
        },
        "MISSING": {"hl_bid": 1, "hl_ask": 2, "bin_bid": 3, "bin_ask": 4},
    }
    monkeypatch.setattr(signaux, "_snapshots_bbo", lambda root: snapshots)
    import hl_observer.experimental.carry_deux_jambes as carry

    monkeypatch.setattr(carry, "frais_venues", lambda root: (2.0, 3.0, "unit"))
    metrics = signaux.metriques_cross_venue(".", now_ms=10_000)
    assert metrics["coins_bbo"] == 3
    assert metrics["coins_frais_1s"] == 1
    assert metrics["frais_source"] == "unit"
    assert metrics["top"][0]["coin"] == "BTC"
    assert metrics["meilleur_net_bps"] == metrics["top"][0]["net_bps"]


def test_lead_lag_fail_closed_and_calibration_without_tape(tmp_path, monkeypatch) -> None:
    class FrozenError(Exception):
        code = "CONFIG_NOT_FOUND"

    monkeypatch.setattr(signaux, "FrozenLeadLagEvidenceError", FrozenError)
    monkeypatch.setattr(signaux, "load_frozen_evidence", lambda path: (_ for _ in ()).throw(FrozenError()))
    sigs, refus = signaux.signaux_lead_lag(tmp_path, now_ms=1_000)
    assert sigs == []
    assert refus[0]["motif"] == "CONFIG_NON_GELEE"

    sigs, refus = signaux.signaux_lead_lag(
        tmp_path,
        now_ms=1_000,
        experimental_calibration=True,
    )
    assert sigs == []
    assert refus == [{"moteur": "lead_lag", "motif": "TAPE_ABSENTE_EXPERIMENTAL"}]


def test_lead_lag_frozen_config_no_positive_horizon(tmp_path, monkeypatch) -> None:
    tape = tmp_path / signaux.TAPE_RELPATH
    tape.parent.mkdir(parents=True)
    tape.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        signaux,
        "load_frozen_evidence",
        lambda path: {
            "coins": ["BTC"],
            "control_coins": [],
            "seuil_choc_bps": 8.0,
            "costs": {"round_trip_bps": 12.0},
            "edge_net_par_horizon_bps": {"1000": -1.0, "2000": 0.0},
            "frequency": {"events_per_day": 1.0},
        },
    )
    sigs, refus = signaux.signaux_lead_lag(tmp_path, now_ms=1_000)
    assert sigs == []
    assert refus == [{"moteur": "lead_lag", "motif": "AUCUN_HORIZON_POSITIF"}]


def test_vault_position_l2_cache_and_retained_helpers(tmp_path) -> None:
    snap = {
        "positions": [
            {"coin": "btc", "szi": "2", "entryPx": "100"},
            {"coin": "ETH", "szi": "-1", "entryPx": None},
            {"coin": "", "szi": 3},
        ]
    }
    assert signaux._positions_par_coin(snap) == {"BTC": (2.0, 100.0), "ETH": (-1.0, 0.0)}

    assert signaux._carnet_l2_frais(tmp_path, now_ms=10_000) == {}
    carnet_path = tmp_path / signaux.CARNET_RELPATH
    carnet_path.parent.mkdir(parents=True, exist_ok=True)
    carnet_path.write_text(
        "\n".join(
            [
                "bad",
                json.dumps({"coin": "BTC", "collecte_ts": 9.5, "hl_bid": 99, "hl_ask": 101}),
                json.dumps({"coin": "OLD", "collecte_ts": 1.0, "hl_bid": 1, "hl_ask": 2}),
            ]
        ),
        encoding="utf-8",
    )
    fresh = signaux._carnet_l2_frais(tmp_path, now_ms=10_000)
    assert set(fresh) == {"BTC"}

    on_demand = signaux._l2_pour_coin_legacy(
        "BTC",
        lecteur_l2=lambda coin: {"hl_bid": 99, "hl_ask": 101, "depth_usd": 50, "age_ms": 1},
        bbo={},
        carnet={},
        now_ms=10_000,
    )
    assert on_demand["src"] == "on_demand"

    bbo = {
        "BTC": {
            "hl_bid": 99,
            "hl_ask": 101,
            "taille_top_usd": 70,
            "collecte_ts": 9.5,
        }
    }
    resolved = signaux._l2_pour_coin_legacy(
        "BTC", lecteur_l2=lambda coin: (_ for _ in ()).throw(OSError("offline")), bbo=bbo, carnet={}, now_ms=10_000
    )
    assert resolved["src"] == "bbo_ws"

    resolved = signaux._l2_pour_coin_legacy(
        "ETH",
        lecteur_l2=None,
        bbo={},
        carnet={"ETH": {"hl_bid": 10, "hl_ask": 11, "taille_min_usd": 80, "collecte_ts": 9.9}},
        now_ms=10_000,
    )
    assert resolved["src"] == "carnet"
    assert signaux._l2_pour_coin_legacy("SOL", lecteur_l2=None, bbo={}, carnet={}, now_ms=10_000) is None

    signaux._filer_coins_au_carnet(tmp_path, [], now_ms=10_000)
    queue = tmp_path / signaux.COINS_BOUGES_RELPATH
    assert not queue.exists()
    signaux._filer_coins_au_carnet(tmp_path, ["btc", "ETH"], now_ms=10_000)
    payload = json.loads(queue.read_text(encoding="utf-8"))
    assert payload["coins"] == {"BTC": 10_000, "ETH": 10_000}

    scores = tmp_path / signaux.SCORES_RELPATH
    assert signaux._vaults_retenus(tmp_path) == set()
    scores.write_text("{", encoding="utf-8")
    assert signaux._vaults_retenus(tmp_path) == set()
    scores.write_text(json.dumps({"retenus": ["v1", "v2"]}), encoding="utf-8")
    assert signaux._vaults_retenus(tmp_path) == {"v1", "v2"}
