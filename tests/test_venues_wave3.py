"""[DATA-085..093] Drift / GMX : normalisation defensive + logique copy-trading (decouverte wallets,
cycle de vie de position, funding par wallet, performance par compte), live-gate honnete."""
import pytest

from hl_observer.venues import drift, gmx
from hl_observer.venues._canon import CleRequiseError, ReseauRequisError, SIDE_ACHAT, SIDE_VENTE


# ---------------- Drift ----------------
def test_drift_trade_defensif():
    out = drift.normalize_trade({"ts": 100, "marketIndex": 0, "oraclePrice": "25.5",
                                 "baseAssetAmount": "3", "direction": "long", "authority": "WALLET_A"})
    assert out["prix"] == 25.5 and out["taille"] == 3.0 and out["side"] == SIDE_ACHAT
    assert out["_extra"]["wallet"] == "WALLET_A"


def test_drift_wallets_actifs_tries():
    trades = [{"authority": "A"}, {"authority": "B"}, {"authority": "A"}, {"wallet": "A"}]
    w = drift.wallets_actifs(trades)
    assert list(w.items())[0] == ("A", 3) and w["B"] == 1


def test_drift_cycle_position():
    events = [{"ts": 1, "type": "open", "size_delta": 5},
              {"ts": 2, "type": "increase", "size_delta": 5},
              {"ts": 3, "type": "close", "size_delta": -10}]
    cy = drift.cycles_position(events)
    assert len(cy) == 1 and cy[0]["ouverture_ts"] == 1 and cy[0]["cloture_ts"] == 3 and cy[0]["raison"] == "flat"


def test_drift_cycle_liquidation_et_ouvert():
    events = [{"ts": 1, "type": "open", "size_delta": 4},
              {"ts": 2, "type": "liquidation", "size_delta": -4},
              {"ts": 3, "type": "open", "size_delta": 2}]
    cy = drift.cycles_position(events)
    assert cy[0]["raison"] == "liquidation"
    assert cy[1]["raison"] == "ouvert" and cy[1]["cloture_ts"] is None


def test_drift_funding_par_wallet():
    pmts = [{"authority": "A", "amount": "1.5"}, {"authority": "A", "amount": "-0.5"},
            {"authority": "B", "amount": "2"}]
    f = drift.funding_par_wallet(pmts)
    assert f["A"] == pytest.approx(1.0) and f["B"] == pytest.approx(2.0)


# ---------------- GMX ----------------
def test_gmx_position_islong():
    p = gmx.normalize_position({"account": "ACC", "market": "ETH", "isLong": True,
                                "sizeInUsd": "10000", "collateralAmount": "1000"})
    assert p["side"] == SIDE_ACHAT and p["taille_usd"] == 10000.0 and p["wallet"] == "ACC"


def test_gmx_trade_short():
    t = gmx.normalize_trade({"account": "ACC", "market": "BTC", "isLong": False,
                             "executionPrice": "60000", "sizeDeltaUsd": "5000", "timestamp": 7})
    assert t["side"] == SIDE_VENTE and t["prix"] == 60000.0


def test_gmx_entites_et_perf():
    reg = gmx.registre_entites({"0xabc": "TeamAlpha"})
    assert reg["resoudre"]("0xabc") == "TeamAlpha" and reg["resoudre"]("0xzzz") == "0xzzz"
    perf = gmx.performance_par_compte([{"account": "A", "realizedPnl": "100"},
                                       {"account": "A", "realizedPnl": "50"},
                                       {"account": "B", "realizedPnl": "200"}])
    assert list(perf.items())[0] == ("B", 200.0) and perf["A"] == 150.0


def test_dex_live_gate():
    with pytest.raises(ReseauRequisError):
        drift.LiveClientDrift().get_trades("SOL-PERP")
    with pytest.raises(ReseauRequisError):
        gmx.LiveClientGMX().query_subgraph("positions")
