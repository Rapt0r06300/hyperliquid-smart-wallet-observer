from __future__ import annotations

import math

import pytest

from hl_observer.research import ofi_microprice as ofi


def _snap(ts: float, mid: float = 100.0, **overrides: float) -> dict[str, float]:
    row = {
        "ts": ts,
        "bid": mid - 0.5,
        "ask": mid + 0.5,
        "mid": mid,
        "micro": mid + 0.1,
        "bid_size": 2.0,
        "ask_size": 1.0,
        "bid_depth": 200.0,
        "ask_depth": 100.0,
    }
    row.update(overrides)
    return row


def test_csv_loader_filters_bad_rows_sorts_and_deduplicates(tmp_path) -> None:
    bad_header = tmp_path / "bad_header.csv"
    bad_header.write_text("coin,ts\nBTC,1\n", encoding="utf-8")
    assert ofi.charger_book_csv(str(bad_header)) == {}

    path = tmp_path / "book.csv"
    path.write_text(
        "coin,ts,bid,ask,mid,micro,bid_size,ask_size,bid_depth_usd,ask_depth_usd,imbalance\n"
        "BTC,2,99,101,100,100.1,2,1,200,100,0.3\n"
        "short,row\n"
        "BTC,bad,99,101,100,100.1,2,1,200,100,0.3\n"
        "BTC,1,99,101,100,,2,1,200,100,0.3\n"
        "BTC,1,98,102,100,100,2,1,200,100,0.3\n"
        "ETH,3,0,1,1,1,1,1,1,1,0\n"
        "SOL,3,2,1,1.5,1.5,1,1,1,1,0\n",
        encoding="utf-8",
    )
    rows = ofi.charger_book_csv(str(path))
    assert list(rows) == ["BTC"]
    assert [row["ts"] for row in rows["BTC"]] == [1.0, 2.0]
    assert math.isnan(rows["BTC"][0]["micro"])


def test_ofi_imbalance_features_and_causal_gap_rules() -> None:
    prev = _snap(1, bid_size=1.0, ask_size=4.0)
    cur = _snap(2, bid_size=3.0, ask_size=2.0)
    assert ofi.ofi_l1(prev, cur) == 4.0
    missing = dict(cur); missing["bid_size"] = float("nan")
    assert math.isnan(ofi.ofi_l1(prev, missing))
    assert ofi._imb(3.0, 1.0) == 0.5
    assert math.isnan(ofi._imb(0.0, 0.0))

    series = [
        _snap(0),
        _snap(1, mid=101.0),
        _snap(100, mid=102.0, micro=float("nan"), bid_size=0.0, ask_size=0.0),
    ]
    feats = ofi.features_causaux(series, dt_max_feat=10)
    assert len(feats) == 2
    assert feats[0]["ofi_l1"] == ofi.ofi_l1(series[0], series[1])
    assert math.isnan(feats[1]["ofi_l1"])
    assert math.isnan(feats[1]["micro_tilt_bps"])
    assert math.isnan(feats[1]["imb_l1"])


def test_markout_skip_gap_cost_direction_and_bucketing() -> None:
    feats = [
        {"ts": 0.0, "mid": 100.0, "spread_bps": 2.0, "dt_prev": 1.0, "x": None},
        {"ts": 1.0, "mid": 101.0, "spread_bps": 2.0, "dt_prev": 1.0, "x": float("nan")},
        {"ts": 2.0, "mid": 102.0, "spread_bps": 2.0, "dt_prev": 1.0, "x": 0.1},
        {"ts": 3.0, "mid": 103.0, "spread_bps": 2.0, "dt_prev": 99.0, "x": 2.0},
        {"ts": 4.0, "mid": 104.0, "spread_bps": float("nan"), "dt_prev": 1.0, "x": -2.0},
        {"ts": 5.0, "mid": 103.0, "spread_bps": 1.0, "dt_prev": 1.0, "x": 1.0},
    ]
    empty = ofi.markout_signal(feats[:4], feature_key="x", seuil=1.0, horizon_pas=1, fee_bps=1.0, dt_max=10)
    assert empty == {"n": 0, "gross_bps": None, "net_bps": None, "events": []}

    result = ofi.markout_signal(feats[4:], feature_key="x", seuil=1.0, horizon_pas=1, fee_bps=1.0, sens=1)
    assert result["n"] == 1
    assert result["gross_bps"] > 0  # short signal while mid falls
    assert result["cout_moyen_bps"] == 1.0  # NaN spread is not charged

    no_spread = ofi.markout_signal(feats[4:], feature_key="x", seuil=1.0, horizon_pas=1, fee_bps=1.0, inclure_spread=False)
    assert no_spread["cout_moyen_bps"] == 1.0

    votes = ofi._votes_par_bucket(
        [
            {"ts": 1, "net_bps": 1},
            {"ts": 2, "net_bps": 3},
            {"ts": 11, "net_bps": -2},
        ],
        bucket_s=10,
    )
    assert votes == [2.0, -2.0]


def test_lcb_house_and_deterministic_fallback(monkeypatch) -> None:
    monkeypatch.setattr(ofi, "_lcb_maison", lambda values: 12.5)
    assert ofi._lcb([1.0]) == 12.5

    monkeypatch.setattr(ofi, "_lcb_maison", None)
    assert ofi._lcb([1.0] * 7) is None
    first = ofi._lcb([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    second = ofi._lcb([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    assert first is not None and first == second


def test_contemporary_diagnostic_insufficient_zero_variance_and_signal() -> None:
    assert ofi.diagnostic_contemporain_ofi([])["note"] == "insuffisant"

    constant_x = [
        {"ofi_l1": 1.0, "dt_prev": 1.0, "mid": 100.0 + i}
        for i in range(31)
    ]
    zero = ofi.diagnostic_contemporain_ofi(constant_x)
    assert zero["note"] == "variance nulle"

    linear = [
        {"ofi_l1": float(i), "dt_prev": 1.0, "mid": 100.0 * (1.0001 ** i)}
        for i in range(31)
    ]
    result = ofi.diagnostic_contemporain_ofi(linear)
    assert result["n"] == 30
    assert result["r2"] is not None and result["beta"] is not None
    assert "non tradable" in result["note"]

    skipped = list(linear)
    skipped[1] = {"ofi_l1": None, "dt_prev": 1.0, "mid": skipped[1]["mid"]}
    assert ofi.diagnostic_contemporain_ofi(skipped)["n"] == 29


def _feature_rows(n: int, *, value: float = 1.0) -> list[dict[str, float]]:
    return [
        {"x": value + (i % 10) / 10.0, "ts": float(i), "mid": 100.0 + i * 0.01, "dt_prev": 1.0, "spread_bps": 1.0}
        for i in range(n)
    ]


def test_experience_feature_all_verdict_branches(monkeypatch) -> None:
    assert ofi.experience_feature(_feature_rows(20), feature_key="x")["raison"] == "trop peu de features valides"

    short_discovery = _feature_rows(200)
    result = ofi.experience_feature(short_discovery, feature_key="x", fraction_decouverte=0.1)
    assert result["raison"] == "decouverte trop courte"

    monkeypatch.setattr(
        ofi,
        "markout_signal",
        lambda feats, **kwargs: {"n": 0, "gross_bps": None, "net_bps": None, "events": []},
    )
    result = ofi.experience_feature(_feature_rows(220), feature_key="x", seuils=[1.0])
    assert result["raison"] == "aucun seuil exploitable en decouverte"

    def markout(feats, **kwargs):
        # Discovery and OOS both contain enough observations; event values make bucketing deterministic.
        return {
            "n": 20,
            "gross_bps": 3.0,
            "net_bps": 2.0,
            "cout_moyen_bps": 1.0,
            "events": [{"ts": float(i * 1000), "net_bps": 2.0} for i in range(20)],
        }

    monkeypatch.setattr(ofi, "markout_signal", markout)
    monkeypatch.setattr(ofi, "_lcb", lambda votes: None)
    more = ofi.experience_feature(_feature_rows(220), feature_key="x", seuils=[1.0], bucket_s=1)
    assert more["verdict"] == "MORE_DATA"

    monkeypatch.setattr(ofi, "_lcb", lambda votes: -0.1)
    killed = ofi.experience_feature(_feature_rows(220), feature_key="x", seuils=[1.0], bucket_s=1)
    assert killed["verdict"] == "KILL"

    monkeypatch.setattr(ofi, "_lcb", lambda votes: 0.5)
    positive = ofi.experience_feature(_feature_rows(220), feature_key="x", seuils=[1.0], bucket_s=1)
    assert positive["verdict"] == "OOS_POSITIF_A_FORWARD"
    assert positive["real_execution"] is False
    assert positive["votes_net_oos"]

    def negative_markout(feats, **kwargs):
        return {
            "n": 20,
            "gross_bps": 0.0,
            "net_bps": -1.0,
            "cout_moyen_bps": 1.0,
            "events": [{"ts": float(i * 1000), "net_bps": -1.0} for i in range(20)],
        }

    monkeypatch.setattr(ofi, "markout_signal", negative_markout)
    negative = ofi.experience_feature(_feature_rows(220), feature_key="x", seuils=[1.0], bucket_s=1)
    assert negative["verdict"] == "KILL"


def test_experience_complete_runs_every_feature(monkeypatch) -> None:
    monkeypatch.setattr(ofi, "features_causaux", lambda serie, dt_max_feat: [{"x": 1}])
    monkeypatch.setattr(ofi, "diagnostic_contemporain_ofi", lambda feats, dt_max: {"ok": True})
    calls: list[str] = []
    monkeypatch.setattr(
        ofi,
        "experience_feature",
        lambda feats, *, feature_key, **kwargs: calls.append(feature_key) or {"feature": feature_key},
    )
    result = ofi.experience_complete([_snap(0), _snap(1)], coin="BTC")
    assert calls == list(ofi.FEATURES)
    assert set(result["par_feature"]) == set(ofi.FEATURES)
    assert result["diagnostic_ofi_contemporain"] == {"ok": True}
