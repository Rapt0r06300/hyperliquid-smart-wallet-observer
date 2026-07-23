"""Filtre anti-perte du flux WS userFills (rectif Flo 23/07) : snapshot initial ignoré + curseur posé ;
après reconnexion, seuls les fills inconnus plus récents que le curseur sont rejoués. Poster injecté."""
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


def test_vaults_et_roles(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "retenus": ["0xC1", "0xC2"],
        "classement": [
            {"vault": "0xC1", "retenu": True, "facteurs": {}},
            {"vault": "0xC2", "retenu": True, "facteurs": {}},
            {"vault": "0xSAFE", "retenu": False, "facteurs": {"anciennete_j": 200, "drawdown_pct": 20, "copyabilite": 0.8}},
            {"vault": "0xOBS", "retenu": False, "facteurs": {"anciennete_j": 5, "drawdown_pct": 20, "copyabilite": 0.8}}]}))
    roles = C.vaults_et_roles(tmp_path)
    d = {v: r for v, r, _w in roles}
    assert d["0xC1"] == "CORE" and d["0xC2"] == "CORE"             # retenus stricts = CORE (tradent)
    assert d["0xSAFE"] == "CANDIDAT_TRADABLE"                       # passe la sécurité mini -> PROBE l'ouvre
    assert d["0xOBS"] == "CANDIDAT_OBSERVE"                         # trop jeune -> observé seulement


def test_depth_executable_somme_5_niveaux_cote_le_plus_mince():
    """Profondeur = somme des 5 premiers niveaux du côté le plus MINCE × mid (plus honnête que le top
    tick seul). Ici bids plus minces que asks -> c'est la somme bids qui décide."""
    rep = {"levels": [
        [{"px": "0.999", "sz": "100"}, {"px": "0.998", "sz": "100"}, {"px": "0.997", "sz": "100"}],   # bids : 300 unités
        [{"px": "1.001", "sz": "500"}, {"px": "1.002", "sz": "500"}]]}                                 # asks : 1000 unités
    d = C._depth_executable(rep, mid=1.0)
    assert abs(d - 300.0) < 1e-6                                    # min(300, 1000) × mid(1.0) = 300 $


def test_depth_executable_carnet_illisible_rend_zero():
    assert C._depth_executable({}, mid=1.0) == 0.0                 # pas de 'levels' -> 0 (jamais inventé)
