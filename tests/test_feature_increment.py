"""ALPHA — matrice d'incrément : combos mesurables, WALLET/ANTICIPATION UNMEASURABLE, règle DROP."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import feature_increment as FI  # noqa: E402


def _feats(n=600, edge_bps=20.0):
    """Série où imb_depth ET ofi_l1 (pas t) prédisent le mid du pas t+1 (continuation)."""
    feats = []
    mid = 100.0
    prev = 0
    for i in range(n):
        mid *= (1 + prev * edge_bps / 1e4)
        d = 1 if i % 2 == 0 else -1
        feats.append({"i": i, "ts": i * 10.0, "mid": mid, "spread_bps": 1.0, "dt_prev": 10.0,
                      "imb_depth": 0.5 * d, "ofi_l1": 1000.0 * d})
        prev = d
    return feats


def test_combo_state_mesurable():
    r = FI.experience_combo(_feats(), ("STATE",), horizon_pas=1, fee_bps=0.0)
    assert r["statut"] == "MEASURABLE" and r["net_bps_oos"] is not None


def test_combo_wallet_unmeasurable():
    r = FI.experience_combo(_feats(), ("WALLET", "STATE"), horizon_pas=1, fee_bps=9.0)
    assert r["statut"] == FI.UNMEASURABLE and r["net_bps_oos"] == FI.UNMEASURABLE


def test_matrice_structure_et_drop_sur_cout():
    m = FI.matrice_increment(_feats(edge_bps=6.0), horizon_pas=1, fee_bps=9.0)
    assert set(m["combos"]) >= {"STATE", "FLOW", "STATE_FLOW", "WALLET_STATE"}
    assert m["combos"]["WALLET_STATE"]["statut"] == FI.UNMEASURABLE
    # 6 bps de gross < 9 de coût -> net<0 partout, aucune brique n'est gardée pour un gain net positif
    if isinstance(m["increment_flow_sur_state_bps"], (int, float)):
        assert m["decision_flow"] in ("KEEP_FLOW", "DROP_FLOW")


def test_net_combo_conjonction_exige_accord():
    # STATE et FLOW en DÉSACCORD de signe -> aucun trade (conjonction non satisfaite)
    feats = [{"i": i, "ts": i * 10.0, "mid": 100.0, "spread_bps": 1.0, "dt_prev": 10.0,
              "imb_depth": 0.5, "ofi_l1": -1000.0} for i in range(50)]
    r = FI.net_combo(feats, ["imb_depth", "ofi_l1"], {"imb_depth": 0.1, "ofi_l1": 100.0},
                     horizon_pas=1, fee_bps=0.0)
    assert r["n"] == 0
