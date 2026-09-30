"""FIX-56 — injection de fautes : chaque panne dégrade honnêtement (0 fill fantôme, 0 crash pour le flux ;
fail-closed pour ledger/disk). La taxonomie est complète (aucune faute non couverte)."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import fault_injection as FI   # noqa: E402


def _events_reels():
    evs, seq = [], 0
    for k in range(20):
        seq += 1
        evs.append({"seq": seq, "ts_ms": 1000 * k, "coin": "BTC", "mid": 100.0 + 0.01 * k})
        if k % 2 == 0:
            seq += 1
            evs.append({"seq": seq, "ts_ms": 1000 * k + 1, "coin": "BTC", "mid": 100.0 + 0.01 * k,
                        "strategy": "lead_lag", "side": 1, "edge_bps": 30.0})
    return evs


def test_fix56_toutes_les_fautes_de_flux_sont_robustes_sans_phantom():
    for faute in FI.FAUTES_FLUX:
        r = FI.resilience_stream(_events_reels(), faute)
        assert r["crash"] is False and r["phantom"] == []        # jamais de crash, jamais de fill fantôme
        assert r["robuste"] is True
        assert r["fills_injectes"] <= r["fills_propres"]         # une faute peut perdre, jamais inventer


def test_fix56_duplicate_filtre_sans_perte_outage_donne_zero():
    dup = FI.resilience_stream(_events_reels(), "DUPLICATE")
    assert dup["fills_injectes"] == dup["fills_propres"]         # doublons dédupliqués : aucune perte, aucun surplus
    out = FI.resilience_stream(_events_reels(), "PROVIDER_OUTAGE")
    assert out["fills_injectes"] == 0 and out["robuste"] is True  # silence total -> 0 trade, jamais de fantôme


def test_fix56_ledger_corrompu_et_disk_error_fail_closed(tmp_path):
    ok = [json.dumps({"equity": 100.0, "cash": 60.0, "positions_val": 40.0})]
    assert FI.verifier_ledger(ok)["statut"] == "OK"
    assert FI.verifier_ledger(['{"equity": 100 PAS_DU_JSON'])["statut"] == "CORROMPU"
    invariant = [json.dumps({"equity": 999.0, "cash": 60.0, "positions_val": 40.0})]
    assert FI.verifier_ledger(invariant)["statut"] == "CORROMPU"    # equity != cash+positions -> refusé
    # disque : fichier absent -> DISK_ERROR (jamais un PnL fabriqué)
    r = FI.lire_ledger(str(tmp_path / "absent.jsonl"))
    assert r["statut"] == "DISK_ERROR"


def test_fix56_taxonomie_complete_8_fautes():
    assert set(FI.FAUTES) == {"WS_DISCONNECT", "GAP", "DUPLICATE", "OUT_OF_ORDER", "STALE",
                              "PROVIDER_OUTAGE", "CORRUPT_LEDGER", "DISK_ERROR"}
    assert set(FI.FAUTES_FLUX).issubset(set(FI.FAUTES))
    # les 2 fautes non-flux (ledger/disk) sont couvertes par des handlers dédiés
    assert {"CORRUPT_LEDGER", "DISK_ERROR"} == set(FI.FAUTES) - set(FI.FAUTES_FLUX)
