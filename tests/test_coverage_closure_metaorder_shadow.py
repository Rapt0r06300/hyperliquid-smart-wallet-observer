from __future__ import annotations

import pytest

import hl_observer.experimental.metaorder_shadow as meta


def _fill(*, time=1000, side="B", coin="BTC", sz="1", px="100", tid=None, oid=None, hash_value=None, crossed=False):
    row = {
        "time": time,
        "side": side,
        "coin": coin,
        "sz": sz,
        "px": px,
        "crossed": crossed,
    }
    if tid is not None:
        row["tid"] = tid
    if oid is not None:
        row["oid"] = oid
    if hash_value is not None:
        row["hash"] = hash_value
    return row


def test_basic_fill_helpers_dedup_and_stable_ids() -> None:
    assert meta.sens_fill({"side": "B"}) == 1
    assert meta.sens_fill({"side": "A"}) == -1
    assert meta.sens_fill({"side": "X"}) == 0
    assert meta.sens_fill(None) == 0
    assert meta.maker_taker({"crossed": True}) == "taker"
    assert meta.maker_taker({"crossed": False}) == "maker"

    one = _fill(tid=1, oid=2, hash_value="0xabc")
    duplicate = dict(one)
    two = _fill(time=1001, tid=3)
    assert meta.dedup_fills([one, duplicate, two]) == [one, two]
    assert meta.metaorder_id("0xA", "btc", 1, 1000) == meta.metaorder_id("0xa", "BTC", 1, 1000)
    assert meta.metaorder_id("0xa", "BTC", 1, 1000).startswith("mo-")
    assert meta.twap_metaorder_id("0xA", "btc", 7).startswith("twap-")


def test_twap_identity_index_lookup_ignores_zero_hash() -> None:
    fill = _fill(tid=11, oid=22, hash_value="0xABC")
    keys = meta._fill_identity_keys(fill)
    assert ("tid", "11") in keys
    assert ("oid_time", "22:1000") in keys
    assert ("hash", "0xabc") in keys

    zero = _fill(tid=None, oid=None, hash_value=meta.ZERO_TWAP_HASH)
    assert meta._fill_identity_keys(zero) == ()

    idx = meta.index_twap([
        {"twapId": 7, "fill": fill},
        {"twapId": None, "fill": _fill(tid=12)},
        None,
    ])
    assert meta.twap_id_fill(fill, idx) == 7
    assert meta.est_twap(fill, idx)
    assert not meta.est_twap(_fill(tid=99), idx)
    assert meta.twap_id_fill({"tid": 5}, {5: "legacy"}) == "legacy"


def test_normalise_twap_states_accepts_channel_and_rejects_invalid() -> None:
    payload = {
        "channel": "twapStates",
        "data": {
            "observed_at_ms": 1234,
            "states": [
                [7, {
                    "coin": "btc",
                    "side": "B",
                    "sz": "10",
                    "executedSz": "4",
                    "executedNtl": "400",
                    "minutes": "2",
                    "timestamp": 1000,
                    "reduceOnly": True,
                    "randomize": False,
                }],
                [8, {"sz": 0}],
                [9, {"sz": "bad"}],
                ["bad"],
                "junk",
            ],
        },
    }
    states = meta.normaliser_twap_states(payload)
    state = states[7]
    assert state["coin"] == "BTC"
    assert state["side"] == "B"
    assert state["total_size"] == 10.0
    assert state["executed_size"] == 4.0
    assert state["fraction_executed"] == 0.4
    assert state["residual_size"] == 6.0
    assert state["normal_slice_size"] == 2.5
    assert state["observed_at_ms"] == 1234
    assert 8 not in states and 9 not in states

    as_list = meta.normaliser_twap_states([[1, {"coin": "ETH", "sz": 2, "minutes": 0}]], observed_at_ms=99)
    assert as_list[1]["normal_slice_size"] == 2.0
    assert as_list[1]["observed_at_ms"] == 99
    assert meta.normaliser_twap_states("bad") == {}


def test_observable_twap_state_is_causal_and_string_id_compatible() -> None:
    snapshots = [
        {"observed_at_ms": 100, "states": [[7, {"coin": "BTC", "sz": 10, "executedSz": 1, "minutes": 1}]]},
        {"observed_at_ms": 200, "states": [["7", {"coin": "BTC", "sz": 10, "executedSz": 5, "minutes": 1}]]},
        {"observed_at_ms": 300, "states": [[7, {"coin": "BTC", "sz": 10, "executedSz": 9, "minutes": 1}]]},
        {"observed_at_ms": "bad", "states": []},
        "junk",
    ]
    state = meta.etat_twap_observable(snapshots, 7, as_of_ms=250)
    assert state["executed_size"] == 5.0
    assert state["observed_at_ms"] == 200
    assert meta.etat_twap_observable([], 7, as_of_ms=250) is None


def test_causal_replay_stages_inferred_reversal_and_direct_twap() -> None:
    inferred = [
        _fill(time=1000, side="B", sz=1, tid=1),
        _fill(time=1100, side="B", sz=2, tid=2),
        _fill(time=1200, side="A", sz=1, tid=3),
        _fill(time=1300, side="X", sz=1, tid=4),
    ]
    rows = meta.rejouer_metaordres_causaux(inferred, vault="v", idx_twap={})
    assert [row["stade"] for row in rows] == ["FIRST_SLICE", "CONTINUATION", "REVERSAL"]
    assert rows[0]["residual_status"] == "RESIDUAL_UNMEASURABLE"
    assert rows[1]["cadence_ms"] == 100
    assert rows[2]["real_execution"] is False and rows[2]["shadow"] is True

    direct = _fill(time=2000, side="B", sz=3, tid=10)
    idx = meta.index_twap([{"twapId": 77, "fill": direct}])
    snapshots = [{
        "observed_at_ms": 2000,
        "states": [[77, {
            "coin": "BTC",
            "side": "B",
            "sz": 4,
            "executedSz": 3,
            "minutes": 1,
            "timestamp": 1000,
        }]],
    }]
    row = meta.rejouer_metaordres_causaux(
        [direct],
        vault="v",
        idx_twap=idx,
        twap_state_snapshots=snapshots,
    )[0]
    assert row["is_twap"] is True
    assert row["stade"] == "LATE_STAGE"
    assert row["fraction_executed"] == 0.75
    assert row["residual_estimated_size"] == 1.0
    assert row["slice_mode"] == "CATCH_UP"
    assert row["eta_ms"] == 59_000


def test_detect_classify_pnl_placebo_ofi_price_and_l2_costs() -> None:
    fills = [
        _fill(time=0, side="B", sz=1),
        _fill(time=10, side="B", sz=2),
        _fill(time=100_000, side="A", sz=3),
        _fill(time=100_001, side="X", sz=1),
    ]
    metas = meta.detecter_metaordres(fills, intervalle_ms=1000)
    assert len(metas) == 2
    assert metas[0]["sz_tot"] == 3.0
    assert metas[1]["reversal"] is True

    assert meta.classer_stade(0, 99, {"reversal": True}) == "REVERSAL"
    assert meta.classer_stade(1, 99, {"fraction_executed": 0.8}) == "LATE_STAGE"
    assert meta.classer_stade(0, 99, {}) == "FIRST_SLICE"
    assert meta.classer_stade(2, 99, {}) == "CONTINUATION"

    assert meta.pnl_forward_net_bps(100, 101, 1, 5) == pytest.approx(95.0)
    assert meta.pnl_forward_net_bps(0, 101, 1, 5) is None
    assert meta.pnl_forward_net_bps("bad", 101, 1, 5) is None
    assert meta.pnl_forward_net_bps(100, None, 1, 5) is None

    placebo = meta.placebo_bps(100, 101, 200, 202, 1)
    assert placebo == {"ret_coin_bps": 100.0, "ret_marche_bps": 100.0, "alpha_vs_marche_bps": 0.0}
    assert meta.placebo_bps(0, 101, 200, 202, 1) is None
    no_market = meta.placebo_bps(100, 101, 0, 202, -1)
    assert no_market["ret_coin_bps"] == -100.0 and no_market["ret_marche_bps"] is None

    before = {"levels": [[{"sz": 1}, {"sz": 2}], [{"sz": 3}]]}
    after = {"levels": [[{"sz": 4}], [{"sz": 1}]]}
    assert meta.ofi_top5(before, after) == 4.0
    assert meta.ofi_top5({}, after) is None

    series = [(10, 1.0), (20, 2.0), (30, 3.0)]
    assert meta.prix_au(series, 5) is None
    assert meta.prix_au(series, 25) == 2.0
    assert meta.prix_au([], 25) is None
    assert meta.prix_au(series, None) is None

    cost, source = meta.cout_l2_reel_bps({"hl_bid": 99, "hl_ask": 101, "depth_usd": 1000}, 100)
    assert cost > 0 and source == "l2_courant_par_taille"
    assert meta.cout_l2_reel_bps(None, 100) == (meta.COUT_AR_DEFAUT_BPS, "screening_16bps")
    assert meta._cout_screening("BTC", 100) == (meta.COUT_AR_DEFAUT_BPS, "screening_16bps")


def test_build_signals_uses_copy_notional_for_cost_and_forward_prices() -> None:
    fills = [_fill(time=1000, side="B", sz=10, px=100, tid=1, crossed=True)]
    seen: list[tuple[str, float]] = []

    def cost_fn(coin, notional):
        seen.append((coin, notional))
        return 5.0, "unit"

    rows = meta.construire_signaux(
        fills,
        vault="v",
        idx_twap={},
        tape_coin=[(1000, 100.0), (2000, 102.0)],
        tape_btc=[(1000, 200.0), (2000, 201.0)],
        cout_fn=cost_fn,
        horizon_ms=1000,
        copy_notional_usd=50,
        maintenant_ms=1500,
    )
    assert seen == [("BTC", 50)]
    row = rows[0]
    assert row["maker_taker"] == "taker"
    assert row["taille_usd"] == 1000.0
    assert row["cout_source"] == "unit"
    assert row["pnl_net_bps"] == pytest.approx(195.0)
    assert row["alpha_vs_marche_bps"] is not None
    assert row["real_execution"] is False
