"""LOT 1 — intégration du plugin DATA dans le superviseur (Flo 25/07).

Prouve : (1) le plugin DATA_CTX s'enregistre (catégorie data, 0 variante) ; (2) via le superviseur, il
collecte avec un poster mocké et écrit la data isolée + une ligne de ledger ; (3) l'ordre data->signal est
respecté ; (4) sa dédup persiste entre deux passes one-shot (processus séparés simulés).
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.research_parallel import registre as REG
from hl_observer.research_parallel import superviseur as SUP
from hl_observer.research_parallel.plugins import lab_data as LD


def _mock_poster():
    m = {
        "metaAndAssetCtxs": [{"universe": [{"name": "BTC"}]},
                             [{"oraclePx": "100", "markPx": "100.5", "openInterest": "1000",
                               "funding": "0.0001", "dayNtlVlm": "5e6", "impactPxs": ["99.9", "100.1"]}]],
        "predictedFundings": [["BTC", [["HlPerp", {"fundingRate": "0.00001"}]]]],
        "perpsAtOpenInterestCap": ["BTC"],
        "clearinghouseState": {"assetPositions": [{"position": {"coin": "BTC", "szi": "5.0"}}]},
    }
    return lambda charge: m[charge["type"]]


def test_data_plugin_enregistre():
    assert LD.PLUGIN.categorie == "data" and LD.PLUGIN.variantes == ()
    assert REG.obtenir("DATA_CTX") is not None


def test_superviseur_collecte_via_le_plugin_data(tmp_path):
    ident = SUP.demarrer(tmp_path, plugins=[LD.PLUGIN])
    res = SUP.tick_tous(tmp_path, ident, {"root": str(tmp_path), "poster": _mock_poster()}, plugins=[LD.PLUGIN])
    assert res["DATA_CTX"]["statut"] == "OK"
    lab = tmp_path / "runtime" / "research_lab" / "data"
    assert (lab / "asset_ctx.jsonl").exists() and (lab / "hlp_inventory.jsonl").exists()
    # une ligne de ledger COLLECTE a été écrite (résumé de la passe)
    led = (tmp_path / "runtime" / "research_lab" / "ledgers" / "DATA_CTX.jsonl")
    assert led.exists() and json.loads(led.read_text().splitlines()[0])["kind"] == "COLLECTE"


def test_ordre_data_avant_signal(tmp_path):
    ordre = []
    data = REG.Plugin(id="D", categorie="data", variantes=(), tick=lambda c: ordre.append("data") or [])
    sig = REG.Plugin(id="S", categorie="signal", variantes=("v",), tick=lambda c: ordre.append("signal") or [])
    ident = SUP.demarrer(tmp_path, plugins=[sig, data])       # donné dans le DÉSORDRE
    SUP.tick_tous(tmp_path, ident, {}, plugins=[sig, data])
    assert ordre == ["data", "signal"], "data collecté avant que les signaux le lisent"


def test_dedup_persiste_entre_passes(tmp_path):
    ctx = {"root": str(tmp_path), "poster": _mock_poster()}
    ident = SUP.demarrer(tmp_path, plugins=[LD.PLUGIN])
    SUP.tick_tous(tmp_path, ident, ctx, plugins=[LD.PLUGIN])
    lab = tmp_path / "runtime" / "research_lab" / "data" / "asset_ctx.jsonl"
    n1 = len(lab.read_text().splitlines())
    # 2e passe = 2e processus simulé : l'état de dédup est RELU du fichier _dedup_etats.json
    SUP.tick_tous(tmp_path, ident, ctx, plugins=[LD.PLUGIN])
    n2 = len(lab.read_text().splitlines())
    assert n1 == 1 and n2 == 1, "données inchangées entre passes -> dédup persistée -> pas de doublon"
