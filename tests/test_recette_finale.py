"""FIX-58 — recette finale : BASE→ADVERSE_P95→ADVERSE_P99, table complète, PROMOTE si TOUS les gates passent,
OPTIMISTIC purement diagnostique (ne promeut JAMAIS)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import recette_economique as RE   # noqa: E402


def _profil(idea, gross, *, lcb=15.0, oos=20.0, fwd=18.0):
    # coût de base = fees+spread+slippage+latency = 7 bps
    return {"idea": idea, "N": 40, "gross_bps": gross, "fees_bps": 3.0, "spread_bps": 2.0,
            "slippage_bps": 1.0, "latency_bps": 1.0, "lcb_net_bps": lcb, "pf": 1.5, "dd": -20.0,
            "es": -12.0, "fill_ratio": 0.9, "capacity_usd": 5000.0, "oos_net_bps": oos, "forward_net_bps": fwd}


def test_fix58_promote_seulement_si_tous_les_gates_passent():
    survivants = [
        _profil("GOOD", 40.0),                       # survit P95/P99, LCB/OOS/forward >0 -> PROMOTE
        _profil("FAIL_P95", 8.0),                    # BASE ~+0.5 mais ADVERSE_P95 négatif -> pas promu
        _profil("FAIL_FWD", 40.0, fwd=-5.0),         # survit P95 mais forward négatif -> pas promu
        _profil("KILL_BASE", 6.0),                   # BASE négatif -> KILL (et optimistic>0 ignoré)
    ]
    r = RE.recette_finale(survivants)
    par = {row["idea"]: row for row in r["table"]}
    assert r["n_promote"] == 1
    g = par["GOOD"]
    assert g["verdict"] == "PROMOTE" and all(g["gates"].values())
    assert g["net_base_bps"] > 0 and g["net_adverse_p95_bps"] > 0 and g["net_adverse_p99_bps"] > 0
    assert par["FAIL_P95"]["verdict"] != "PROMOTE" and par["FAIL_P95"]["gates"]["adverse_p95"] is False
    fwd = par["FAIL_FWD"]
    assert fwd["verdict"] != "PROMOTE" and fwd["gates"]["adverse_p95"] is True and fwd["gates"]["forward_positif"] is False


def test_fix58_optimistic_ne_promeut_jamais():
    # BASE négatif mais OPTIMISTIC positif : l'optimiste ne doit JAMAIS sauver la promotion
    kill = RE.recette_finale([_profil("OPTI_ONLY", 6.0)])["table"][0]
    assert kill["net_optimistic_diag_bps"] > 0 and kill["verdict"] == "KILL"    # optimiste positif mais KILL


def test_fix58_table_complete_et_sans_survivant():
    row = RE.recette_finale([_profil("X", 40.0)])["table"][0]
    for col in RE.COLONNES_FINALES:                  # table complète : chaque colonne FIX-58 présente
        assert col in row
    vide = RE.recette_finale([])
    assert vide["n_survivants"] == 0 and vide["n_promote"] == 0 and vide["real_execution"] is False
