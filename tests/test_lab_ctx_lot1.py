"""LOT 1 — collecteur de données du labo, prouvé sans réseau (Flo 25/07).

Prouve : (1) les parsers extraient predictedFundings / perpsAtOpenInterestCap / clearinghouseState ;
(2) une_passe écrit les 4 flux SOUS research_lab/data (isolé de runtime/data) avec provenance+checksum ;
(3) la dédup n'écrit que les CHANGEMENTS (borne la croissance sans perdre d'info) ; (4) un flux KO
n'empêche pas les autres ; (5) les fichiers grossissent réellement passe après passe.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("clc", _ROOT / "tools" / "collecter_lab_ctx.py")
LC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LC)


def test_parser_predicted_fundings():
    payload = [["BTC", [["HlPerp", {"fundingRate": "0.0000125", "nextFundingTime": 1785000000000}],
                        ["BinPerp", {"fundingRate": "0.00005", "nextFundingTime": 1785000000000}]]],
               ["SOL", [["HlPerp", {"fundingRate": "-0.0001"}]]]]
    r = LC.parser_predicted_fundings(payload)
    assert {(x["coin"], x["venue"]) for x in r} == {("BTC", "HlPerp"), ("BTC", "BinPerp"), ("SOL", "HlPerp")}
    assert any(abs(x["taux"] - 0.00005) < 1e-9 for x in r)


def test_parser_oi_cap_et_hlp_inventory():
    assert LC.parser_oi_cap(["kPEPE", "BTC", "kPEPE"]) == ["BTC", "KPEPE"]
    ch = {"assetPositions": [{"position": {"coin": "ETH", "szi": "-12.5", "entryPx": "3000", "positionValue": "37500"}}]}
    inv = LC.parser_hlp_inventory(ch, addr="0xdeadbeef00")
    assert inv[0]["coin"] == "ETH" and inv[0]["szi"] == -12.5 and inv[0]["position_value"] == 37500.0


def _poster(payload_map):
    def _p(charge):
        return payload_map[charge["type"]]
    return _p


def _mock_map():
    return {
        "metaAndAssetCtxs": [{"universe": [{"name": "BTC"}]},
                             [{"oraclePx": "100", "markPx": "100.5", "openInterest": "1000",
                               "funding": "0.0001", "dayNtlVlm": "5e6", "impactPxs": ["99.9", "100.1"]}]],
        "predictedFundings": [["BTC", [["HlPerp", {"fundingRate": "0.00001"}]]]],
        "perpsAtOpenInterestCap": ["BTC"],
        "clearinghouseState": {"assetPositions": [{"position": {"coin": "BTC", "szi": "5.0"}}]},
    }


def test_une_passe_ecrit_isole_et_provenance(tmp_path):
    res = LC.une_passe(tmp_path, poster=_poster(_mock_map()), etats={})
    lab = tmp_path / "runtime" / "research_lab" / "data"
    assert (lab / "asset_ctx.jsonl").exists() and (lab / "predicted_fundings.jsonl").exists()
    assert (lab / "oi_cap.jsonl").exists() and (lab / "hlp_inventory.jsonl").exists()
    # ISOLATION : rien sous runtime/data (main)
    assert not (tmp_path / "runtime" / "data").exists()
    l = json.loads((lab / "asset_ctx.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert l["real_execution"] is False and "ts_mono_ns" in l and len(l["checksum"]) == 12
    assert res["asset_ctx"] == 1 and res["oi_cap"] == 1 and res["hlp_inventory"] == 1


def test_dedup_n_ecrit_que_les_changements(tmp_path):
    etats: dict = {}
    poster = _poster(_mock_map())
    LC.une_passe(tmp_path, poster=poster, etats=etats)
    n1 = len((tmp_path / "runtime" / "research_lab" / "data" / "asset_ctx.jsonl").read_text().splitlines())
    LC.une_passe(tmp_path, poster=poster, etats=etats)          # MÊMES données -> dédup -> rien de neuf
    n2 = len((tmp_path / "runtime" / "research_lab" / "data" / "asset_ctx.jsonl").read_text().splitlines())
    assert n1 == 1 and n2 == 1, "données inchangées -> pas de doublon (dédup)"
    # un changement (premium bouge) -> nouvelle ligne
    m = _mock_map(); m["metaAndAssetCtxs"][1][0]["markPx"] = "101.0"
    LC.une_passe(tmp_path, poster=_poster(m), etats=etats)
    n3 = len((tmp_path / "runtime" / "research_lab" / "data" / "asset_ctx.jsonl").read_text().splitlines())
    assert n3 == 2, "un changement réel EST écrit (on ne perd aucune info)"


def test_un_flux_KO_n_empeche_pas_les_autres(tmp_path):
    m = _mock_map()
    def _p(charge):
        if charge["type"] == "predictedFundings":
            raise OSError("réseau coupé sur ce flux")
        return m[charge["type"]]
    res = LC.une_passe(tmp_path, poster=_p, etats={})
    assert str(res["predicted_fundings"]).startswith("KO")
    assert res["asset_ctx"] == 1 and res["oi_cap"] == 1, "les autres flux passent malgré un flux KO"


def test_les_fichiers_grossissent_passe_apres_passe(tmp_path):
    lab = tmp_path / "runtime" / "research_lab" / "data" / "hlp_inventory.jsonl"
    etats: dict = {}
    tailles = []
    for i in range(3):
        m = _mock_map(); m["clearinghouseState"]["assetPositions"][0]["position"]["szi"] = str(5.0 + i)  # change
        LC.une_passe(tmp_path, poster=_poster(m), etats=etats)
        tailles.append(lab.stat().st_size)
    assert tailles[0] < tailles[1] < tailles[2], "le fichier grossit réellement à chaque changement"
