"""Gel versionné de la table préliminaire (rectif Flo 23/07) : le forward ne se réoptimise jamais.
On prouve : gel de la table live, puis REFUS d'écraser (gel définitif), + forçage possible."""
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


GP = _mod("geler_prelim_copie")


def test_gel_puis_refus_ecrasement(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "copy_prelim_edge.json").write_text(json.dumps(
        {"source_prix": "candles_5m", "table": {"AVAX": {"net_bps": 24.6, "stop_bps": 30.0}}}))
    r1 = GP.geler(tmp_path)
    assert r1["statut"] == "GELE" and r1["coins"] == ["AVAX"] and (tmp_path / GP.GELE).exists()
    # 2e appel : gel DÉFINITIF, on n'écrase pas
    r2 = GP.geler(tmp_path)
    assert r2["statut"] == "DEJA_GELE"
    # --forcer réécrit
    assert GP.geler(tmp_path, forcer=True)["statut"] == "GELE"


def test_pas_de_table_live(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    assert GP.geler(tmp_path)["statut"] == "PAS_DE_TABLE_LIVE"
