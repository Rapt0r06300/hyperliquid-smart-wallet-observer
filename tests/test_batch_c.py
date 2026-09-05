"""ALPHA batch C — familles recherche : price discovery, cross-asset, universal micro, nonlinear,
metaorder hazard, liquidation flow, cascade warning, clock regimes, wallet fingerprint, abnormal regime."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import abnormal_regime as AR  # noqa: E402
from hl_observer.research import cascade_warning as CW  # noqa: E402
from hl_observer.research import clock_regimes as CR  # noqa: E402
from hl_observer.research import cross_asset_leadlag as CA  # noqa: E402
from hl_observer.research import liquidation_flow as LF  # noqa: E402
from hl_observer.research import metaorder_hazard as MH  # noqa: E402
from hl_observer.research import nonlinear_challenger as NL  # noqa: E402
from hl_observer.research import price_discovery as PD  # noqa: E402
from hl_observer.research import universal_micro as UM  # noqa: E402
from hl_observer.research import wallet_fingerprint as WF  # noqa: E402


def test_price_discovery_a_mene():
    a = [(1.0 if i % 2 == 0 else -1.0) for i in range(200)]
    b = [0.0] + a[:-1]                                    # b suit a d'un pas
    assert PD.crosscorr_lead(a, b, max_lag=3)["a_mene"] is True
    sc = PD.venue_leader_score({"A": a, "B": b}, max_lag=3)
    assert sc["A"] >= sc["B"]


def test_cross_asset_beta_neutre():
    lead = [(1.0 if i % 3 == 0 else -0.5) for i in range(100)]
    follow = [2.0 * x for x in lead]                      # pur beta, pas de residu predictif
    r = CA.leadlag_beta_neutre(lead, follow, horizon=1)
    assert r["beta"] is not None


def test_universal_micro_transferable():
    par_coin = {}
    for c in ("BTC", "ETH", "SOL"):
        f = [(1.0 if i % 2 == 0 else -1.0) for i in range(40)]
        t = [20.0 * x for x in f]                         # feature predit fortement (target 20 bps)
        par_coin[c] = (f, t)
    r = UM.leave_one_coin_out(par_coin, cout_bps=9.0)
    assert r["verdict"] in ("TRANSFERABLE_A_OOS", "KILL", "MORE_DATA")


def test_nonlinear_challenger_verdict():
    f = [(1.0 if i % 2 == 0 else -1.0) for i in range(120)]
    t = [15.0 * x for x in f]
    r = NL.challenger(f, t, cout_bps=9.0)
    assert r["verdict"] in ("CHALLENGER_UTILE", "BASELINE_SUFFIT", "MORE_DATA")


def test_metaorder_hazard():
    assert MH.flux_residuel(1000.0, 0.3) == 700.0
    r = MH.remaining_flow_probability(stade="FIRST_SLICE", executed_fraction=0.1, crowding=0.1)
    assert r["p_continuation"] > 0.5 and r["favorable_EARLY_LARGE_RESIDUAL_LOW_CROWDING"] is True


def test_liquidation_cascade():
    liqs = [{"ts_ms": 1000 * i, "side": -1, "notional_usd": 1000} for i in range(4)]
    r = LF.analyser(liqs, fenetre_ms=5000, seuil_amas=3)
    assert r["regime"] == "LIQUIDATION_CASCADE" and r["sens_dominant"] == -1


def test_cascade_warning():
    r = CW.warning_score(taker_flow_compression=0.9, price_autocorr=0.8, depth_thinning=0.7)
    assert r["regime"] == "PRUDENCE_PRE_CASCADE"
    assert CW.warning_score()["score"] == CW.UNMEASURABLE


def test_clock_regimes():
    assert CR.bucket_horloge(1234, "seconde") == 234
    assert CR.session_utc(0) == "ASIE"
    buckets = {"a": [10.0] * 10, "b": [-5.0] * 10}
    r = CR.tester_buckets(buckets)
    assert r["meilleur"] == "a" and "verdict" in r


def test_wallet_fingerprint():
    fills = [{"ts_ms": i * 1000, "coin": "BTC", "maker": True} for i in range(10)]
    fp = WF.fingerprint(fills)
    assert fp["n_coins"] == 1 and fp["maker_ratio"] == 1.0
    emp = {"0xA": fp, "0xB": WF.fingerprint([{"ts_ms": i * 1000, "coin": "BTC", "maker": True} for i in range(10)])}
    assert WF.entites_communes(emp)                       # deux wallets identiques -> meme entite


def test_abnormal_regime():
    r = AR.regime_anormal(age_listing_h=2.0, spread_bps=5.0, depth_usd=10000.0)
    assert r["anormal"] is True and "NOUVEAU_LISTING" in r["raisons"] and r["action"] == "NO_TRADE"
    assert AR.regime_anormal(age_listing_h=100.0, spread_bps=5.0, depth_usd=10000.0)["anormal"] is False

    fail_closed = AR.regime_anormal(
        delisting=True,
        tick_ou_lot_change=True,
        age_listing_h=100.0,
        spread_bps=5.0,
        depth_usd=1000.0,
    )
    assert fail_closed["anormal"] is True
    assert fail_closed["action"] == "NO_TRADE"
    assert {"DELISTING", "TICK_OU_LOT_CHANGE", "ILLIQUIDE"} <= set(fail_closed["raisons"])
