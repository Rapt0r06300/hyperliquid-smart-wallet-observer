"""Tests de la réconciliation croisée des sources de fills (pur)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import reconcilier_sources as R  # noqa: E402

NOW = 1_800_000_000_000


def test_cle_identite_par_tid_puis_repli():
    a = R.cle_identite({"vault": "0xA", "coin": "ETH", "tid": 42})
    b = R.cle_identite({"user": "0xA", "coin": "ETH", "tid": 42})  # vault/user, même id
    assert a == b and a[2][0] == "id"
    repli = R.cle_identite({"vault": "0xA", "coin": "ETH", "ts_ms": NOW, "px": "2000", "sz": "1"})
    assert repli is not None and repli[2][0] == "ts"
    assert R.cle_identite({"coin": "ETH"}) is None  # pas de vault


def test_reconcilier_overlap_et_trous():
    ws = [{"vault": "0xA", "coin": "ETH", "tid": 1}, {"vault": "0xA", "coin": "ETH", "tid": 2}]
    node = [{"vault": "0xA", "coin": "ETH", "tid": 2}, {"vault": "0xB", "coin": "BTC", "tid": 9}]
    rap = R.reconcilier({"ws": ws, "node": node})
    assert rap["par_source"] == {"ws": 2, "node": 2}
    assert rap["union_unique"] == 3          # tid1, tid2, tid9
    assert rap["exclusifs_par_source"]["ws"] == 1    # tid1
    assert rap["exclusifs_par_source"]["node"] == 1  # tid9
    assert rap["trous"]["node_absents_de_ws"] == 1   # tid9 raté par ws
    assert rap["trous"]["ws_absents_de_node"] == 1   # tid1 raté par node
    assert rap["vaults_avec_fill"] == 2


def test_couverture_leaders_actifs():
    ws = [{"vault": "0xA", "coin": "ETH", "tid": 1}]
    rap = R.reconcilier({"ws": ws}, users_actifs={"0xA", "0xB", "0xC"})
    assert rap["leaders_actifs_vus"] == 3
    assert rap["leaders_actifs_sans_fill"] == 2       # 0xB, 0xC actifs mais 0 fill capté
    assert set(rap["echantillon_sans_fill"]) == {"0xb", "0xc"}
