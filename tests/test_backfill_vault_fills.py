"""Backfill CLI userFillsByTime (rectif Flo 23/07) : cibles = retenus + témoin (deny-by-default si pas
de score), pagination + parsing + dédup d'UN vault avec poster INJECTÉ (aucun réseau)."""
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


BF = _mod("backfill_vault_fills")


def test_vaults_cibles_retenus_et_temoin(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "retenus": ["0xR1", "0xR2"],
        "classement": [{"vault": "0xR1", "retenu": True}, {"vault": "0xN1", "retenu": False},
                       {"vault": "0xN2", "retenu": False}]}))
    retenus, temoin = BF.vaults_cibles(tmp_path)
    assert retenus == ["0xR1", "0xR2"] and temoin == ["0xN1", "0xN2"]
    assert BF.vaults_cibles(tmp_path / "vide") == ([], [])            # pas de score -> deny-by-default


def test_backfill_un_vault_pagine_parse_dedup(tmp_path):
    from hl_observer.collection import collecte_fiable as CF
    appels = {"n": 0}

    def faux_poster(vault, a, b):
        appels["n"] += 1
        return [{"time": 1000, "coin": "SOL", "px": "150", "sz": "10", "side": "B",
                 "dir": "Open Long", "startPosition": "0", "oid": 1}]   # même fill à chaque fenêtre

    fills = BF.backfill_un_vault(tmp_path, "0xR1", lookback_j=2, limiteur=CF.Limiteur(0.0), poster=faux_poster)
    assert appels["n"] >= 2                                            # plusieurs fenêtres paginées
    assert len(fills) == 1 and fills[0]["coin"] == "SOL"              # doublons dédupliqués
