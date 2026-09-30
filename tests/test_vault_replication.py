"""BACKTEST RÉPLICATION COPY-VAULTS (chantier COPY, 23/07). On prouve : le rendement est CORRIGÉ des
dépôts/retraits (un dépôt n'est pas un gain), le turnover est facturé au bid/ask, et les vaults REJETÉS
servent de contrôle anti-survivorship. Snapshots synthétiques, aucun réseau."""
from __future__ import annotations

import json

from hl_observer.backtesting.vault_replication import repliquer, backtest, charger_snapshots_vault


def _snaps(vault, nav0, nav1, *, depot=0.0, dexpo=0.0, n=12):
    out = []
    for i in range(n):
        nav = nav0 + (nav1 - nav0) * i / (n - 1)
        out.append({"vault": vault, "ts_ms": i * 86_400_000, "nav_usd": nav,
                    "depot_retrait_net_usd": depot if i == 3 else 0.0,
                    "delta_expo_nette_usd": dexpo})
    return out


def test_rendement_est_CORRIGE_des_depots():
    # NAV 10000 -> 11000 MAIS 500 de dépôt : le vrai rendement = (1000-500)/10000 = +500 bps, pas +1000
    r = repliquer(_snaps("0xv", 10000.0, 11000.0, depot=500.0, dexpo=1000.0))
    assert r["verdict"] == "MESURE"
    assert 498.0 < r["rendement_corrige_bps"] < 502.0        # dépôt retiré
    assert r["cout_turnover_bps"] > 0 and r["net_replique_bps"] < r["rendement_corrige_bps"]


def test_moins_de_12_snapshots_est_INSUFFISANT():
    assert repliquer(_snaps("0xv", 10000.0, 11000.0, n=5))["verdict"] == "INSUFFISANT"


def test_backtest_compare_RETENUS_vs_CONTROLE_anti_survivorship(tmp_path):
    p = tmp_path / "runtime" / "data" / "vault_snapshots.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = _snaps("0xBON", 10000.0, 11000.0, dexpo=200.0)     # retenu : +~1000 bps net
    rows += _snaps("0xREJETE", 10000.0, 10050.0, dexpo=200.0)  # contrôle : ~+50 bps
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    r = backtest(tmp_path, vaults_retenus=["0xBON"], vaults_controle=["0xREJETE"])
    assert r["statut"] == "PROMETTEUR" and r["bat_le_controle"]
    assert r["net_median_retenus_bps"] > r["net_median_controle_bps"]


def test_backtest_NEED_MORE_DATA_sans_snapshots(tmp_path):
    assert backtest(tmp_path)["statut"] == "NEED_MORE_DATA"
    assert charger_snapshots_vault(tmp_path) == {}
