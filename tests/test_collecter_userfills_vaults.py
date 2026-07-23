"""Filtre anti-perte du flux WS userFills (rectif Flo 23/07) : snapshot initial ignoré + curseur posé ;
après reconnexion, seuls les fills inconnus plus récents que le curseur sont rejoués. Poster injecté."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _mod("collecter_userfills_vaults")


def _f(ts, snap=False):
    return {"coin": "SOL", "ts_ms": ts, "isSnapshot": snap, "hash": "h%d" % ts}


def test_snapshot_initial_ignore_et_curseur_pose():
    cur = {}
    a = C.fills_a_traiter("0xV", [_f(100, snap=True), _f(200, snap=True)], cur)
    assert a == [] and cur["0xV"] == 200                            # rien tradé, curseur = dernier ts


def test_reconnexion_rejoue_les_inconnus_recents():
    cur = {"0xV": 200}
    # snapshot de reconnexion : fills 150 (déjà vu) et 300 (survenu pendant la coupure)
    a = C.fills_a_traiter("0xV", [_f(150, snap=True), _f(300, snap=True)], cur)
    assert [f["ts_ms"] for f in a] == [300] and cur["0xV"] == 300   # catch-up : seulement le récent


def test_live_filtre_sur_curseur():
    cur = {"0xV": 300}
    a = C.fills_a_traiter("0xV", [_f(300), _f(400), _f(500)], cur)  # 300 = curseur (pas strictement >)
    assert [f["ts_ms"] for f in a] == [400, 500] and cur["0xV"] == 500
