"""CHANTIER #3 — collecte TWAP userTwapSliceFills : fraction exécutée + branchement metaorder hazard."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import twap_collector as TW   # noqa: E402


def test_chantier3_slices_alimentent_le_hazard(tmp_path):
    # un TWAP total 1000, 5 slices de 200 -> fraction 0.2/0.4/0.6/0.8/1.0 ; flux résiduel décroît vers 0.
    slices = [{"twap_id": "T1", "coin": "BTC", "side": "B", "executedSz": 200, "executedNtl": 20000,
               "total_size": 1000, "time": 1000 + i} for i in range(5)]
    out = tmp_path / "twap.jsonl"
    r = TW.collecter_twap(slices, str(out))
    assert r["statut"] == "OK" and r["n_slices"] == 5 and r["n_twaps"] == 1
    dernier = r["exemple"]
    assert dernier["executed_fraction"] == 1.0 and dernier["flux_residuel"] == 0.0   # résidu nul en fin de TWAP
    assert 0.0 <= dernier["hazard"]["p_continuation"] <= 1.0 and out.exists()


def test_chantier3_stade_early_a_haute_continuation(tmp_path):
    r = TW.collecter_twap([{"twap_id": "T2", "coin": "ETH", "side": "S", "executedSz": 100,
                            "total_size": 1000, "time": 1}], None)
    ex = r["exemple"]
    assert ex["executed_fraction"] == 0.1 and ex["flux_residuel"] == 900.0
    assert ex["hazard"]["p_continuation"] > 0.5              # tôt + petit exécuté -> forte proba de résidu


def test_chantier3_sans_source_est_blocked_external():
    assert TW.collecter_twap(None)["statut"] == "BLOCKED_EXTERNAL"
    assert TW.slice_canonique({"coin": "BTC"}) is None       # twap_id manquant -> jamais une slice fabriquée
