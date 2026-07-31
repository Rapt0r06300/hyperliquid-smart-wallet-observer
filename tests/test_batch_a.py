"""ALPHA batch A — deconfliction, meta_gate, wallet_info_ratio, capital_efficiency, daily_report, drift_detector."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import capital_efficiency as CE  # noqa: E402
from hl_observer.research import daily_report as DR  # noqa: E402
from hl_observer.research import deconfliction as DC  # noqa: E402
from hl_observer.research import drift_detector as DD  # noqa: E402
from hl_observer.research import meta_gate as MG  # noqa: E402
from hl_observer.research import wallet_info_ratio as WI  # noqa: E402


def test_deconfliction_regroupe_meme_coin():
    sig = [{"coin": "BTC", "ts_ms": 0, "type": "wallet"}, {"coin": "BTC", "ts_ms": 500, "type": "ofi"},
           {"coin": "BTC", "ts_ms": 5000, "type": "twap"}, {"coin": "ETH", "ts_ms": 100, "type": "wallet"}]
    r = DC.deconflicter(sig, fenetre_ms=1000)
    assert r["n_clusters"] == 3                             # BTC{0,500} fusionnes, BTC{5000}, ETH
    assert r["facteur_sur_comptage"] > 1.0


def test_meta_gate_garde_composante_utile():
    r = MG.meta_gate(10.0, {"wallet": 3.0, "ofi": 9.5})     # retirer wallet -> 3 (chute 7) ; retirer ofi -> 9.5 (chute 0.5)
    assert "wallet" in r["gardees"] and r["verdict"] == "COMBINER"


def test_wallet_info_ratio_net_negatif_zero():
    assert WI.info_ratio(lead_time_ms=1000, copyable_gross_bps=5.0, cout_bps=9.0)["score"] == 0.0
    bon = WI.info_ratio(lead_time_ms=1500, copyable_gross_bps=25.0, stability=0.8, entity_independent=True)
    assert bon["score"] > 0


def test_capital_efficiency():
    assert CE.net_edge_per_margin_hour(50.0, 500.0, 2.0) == 0.05
    assert CE.net_edge_per_margin_hour(50.0, 0.0, 2.0) == CE.UNMEASURABLE


def test_daily_report_synthese():
    rows = [{"verdict": "KILL"}, {"verdict": "KILL"}, {"verdict": "CANDIDAT", "idea": "x"}]
    s = DR.synthese(rows)
    assert s["par_verdict"]["KILL"] == 2 and s["n_candidats"] == 1
    assert "rapport" in DR.rapport_markdown(rows)


def test_drift_detector_demote():
    serie = [10.0] * 20 + [2.0] * 20                        # edge s'effondre
    assert DD.detecter_drift(serie, fenetre=20)["statut"] == "DEMOTE"
    stable = [10.0] * 40
    assert DD.detecter_drift(stable, fenetre=20)["statut"] == "OK"
