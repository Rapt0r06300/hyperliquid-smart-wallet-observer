"""Outil de scoring des vaults (rectif Flo 23/07) : il applique le score 8-facteurs aux vaults
snapshotés, récupère age/tvl depuis la provenance, calcule les coins exécutables (carnet ∪ BBO),
et publie retenus + classement. On prouve qu'un vault à gros drawdown est REJETÉ (piège APR)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SV = _mod("scorer_vaults")


def _ecrire(root, snaps, provenance=None, carnet=None):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        "\n".join(json.dumps(s) for s in snaps), encoding="utf-8")
    if provenance is not None:
        (root / "runtime" / "data" / "vaults_suivis.json").write_text(
            json.dumps({"_provenance": {"vaults": provenance}, "vaults": [v["address"] for v in provenance]}))
    if carnet is not None:
        (root / "runtime" / "data" / "carnet_venues.jsonl").write_text(
            "\n".join(json.dumps(c) for c in carnet), encoding="utf-8")


def test_coins_executables_carnet_union_bbo(tmp_path):
    _ecrire(tmp_path, [], carnet=[{"coin": "HYPE"}, {"coin": "FARTCOIN"}])
    exe = SV.coins_executables(tmp_path)
    assert "BTC" in exe and "HYPE" in exe and "FARTCOIN" in exe        # BBO ∪ carnet


def test_construire_retient_le_bon_rejette_le_drawdown(tmp_path):
    bon = [{"vault": "0xBON", "ts_ms": 1000 * i, "nav_usd": nav, "drawdown_pct": 5.0,
            "positions": [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}]}
           for i, nav in enumerate([100_000, 101_000, 102_000])]
    # même rendement mais drawdown catastrophique (piège APR) -> doit être rejeté
    piege = [{"vault": "0xPIEGE", "ts_ms": 1000 * i, "nav_usd": nav, "drawdown_pct": 80.0,
              "positions": [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}]}
             for i, nav in enumerate([100_000, 101_000, 102_000])]
    prov = [{"address": "0xBON", "age_j": 300, "tvl_usd": 3_000_000},
            {"address": "0xPIEGE", "age_j": 400, "tvl_usd": 5_000_000}]
    _ecrire(tmp_path, bon + piege, provenance=prov, carnet=[{"coin": "BTC"}])
    p = SV.construire(tmp_path)
    assert "0xBON" in p["retenus"] and "0xPIEGE" not in p["retenus"]
    piege_row = next(c for c in p["classement"] if c["vault"] == "0xPIEGE")
    assert piege_row["raison"] == "DRAWDOWN_EXCESSIF"
    assert SV.ecrire(tmp_path, p) == p["n_retenus"] and (tmp_path / SV.SORTIE).exists()
