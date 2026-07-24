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


def test_rotation_10_places_2_core_8_candidats_par_activite(tmp_path):
    """10 places WS : 2 CORE + 8 candidats, ROTATION par activité live. À copyabilité égale, le candidat
    le PLUS ACTIF passe devant, et on plafonne à 8 candidats (12 en lice)."""
    import time
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    now = time.time() * 1000
    cl = [{"vault": "0xC1", "retenu": True, "facteurs": {}}, {"vault": "0xC2", "retenu": True, "facteurs": {}}]
    for i in range(3, 15):                                          # 12 candidats non-core
        cl.append({"vault": "0x%02d" % i, "retenu": False,
                   "facteurs": {"anciennete_j": 5, "drawdown_pct": 20, "copyabilite": 0.8}})
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({"retenus": ["0xC1", "0xC2"], "classement": cl}))
    fills = [{"vault": "0x14", "coin": "WLD", "ts_ms": now - 1000} for _ in range(20)]     # très actif
    fills += [{"vault": "0x03", "coin": "WLD", "ts_ms": now - 1000}]                        # peu actif
    (tmp_path / "runtime" / "data" / "vault_fills_live.jsonl").write_text("\n".join(json.dumps(x) for x in fills))
    vaults = [v for v, _r, _w in C.vaults_et_roles(tmp_path)]
    assert vaults[:2] == ["0xC1", "0xC2"] and len(vaults) == 10     # 2 CORE + 8 candidats (10 places)
    cand = vaults[2:]
    assert "0x14" in cand and cand.index("0x14") < cand.index("0x03")   # le plus actif passe devant


def test_parse_l2_ws_rend_bid_ask_depth():
    d = {"coin": "WLD", "levels": [
        [{"px": "0.385", "sz": "1000"}, {"px": "0.384", "sz": "1000"}],   # bids
        [{"px": "0.386", "sz": "1000"}, {"px": "0.387", "sz": "1000"}]]}   # asks
    b = C._parse_l2_ws(d)
    assert b and abs(b[0] - 0.385) < 1e-9 and abs(b[1] - 0.386) < 1e-9 and b[2] > 0   # (bid, ask, depth>0)
    assert C._parse_l2_ws({"coin": "X"}) is None                          # illisible -> None (jamais inventé)


def test_book_ws_frais_prefere_au_marquage(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(C, "_ROOT_LIVE", tmp_path)
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / C.RAW_L2_LIVE).write_text(json.dumps(
        {"WLD": {"hl_bid": 0.385, "hl_ask": 0.386, "depth_usd": 3000.0, "collecte_ts": time.time()}}))
    b = C._book_ws_frais("WLD")
    assert b and b["hl_bid"] == 0.385 and b["hl_ask"] == 0.386             # book WS frais servi
    assert C._lecteur_l2_marquage("WLD")["hl_bid"] == 0.385               # marquage préfère le book WS (pas de REST)
    (tmp_path / C.RAW_L2_LIVE).write_text(json.dumps(
        {"WLD": {"hl_bid": 0.385, "hl_ask": 0.386, "depth_usd": 3000.0, "collecte_ts": time.time() - 10}}))
    assert C._book_ws_frais("WLD") is None                                # périmé -> None (pas de fraîcheur inventée)


def test_vault_du_message_demux_multiplex():
    """Multiplex userFills : on démux par data.user, mappé sur la forme canonique abonnée (casse insensible)."""
    connus = {v.lower(): v for v in ["0xAbCdEf01", "0x12345678"]}
    m = {"channel": "userFills", "data": {"user": "0xabcdef01", "fills": []}}
    assert C._vault_du_message(m, connus) == "0xAbCdEf01"                 # casse insensible -> canonique abonné
    assert C._vault_du_message({"data": {"user": "0xZZZZ"}}, connus) is None   # user inconnu -> None
    assert C._vault_du_message({"data": {}}, connus) is None              # pas de user -> None
    assert C._vault_du_message({"channel": "x"}, connus) is None          # message sans data -> None


def test_shards_userfills_disjoints_de_5():
    """Sharding DÉTERMINISTE en groupes de 5 (HL cape ~5/connexion) : 2 sockets A/B disjoints couvrant tout."""
    vaults = ["0xv%02d" % i for i in range(10)]
    shards = C._shards_userfills(vaults, taille=5)
    assert [s for s, _ in shards] == ["A", "B"] and len(shards) == 2   # 2 sockets
    a, b = shards[0][1], shards[1][1]
    assert a == vaults[:5] and b == vaults[5:]                        # déterministe, 5 chacun
    assert set(a).isdisjoint(set(b)) and set(a) | set(b) == set(vaults)   # DISJOINTS + couvrent tout (pas de doublon)
    # 8 vaults -> A(5) + B(3)
    assert [len(g) for _, g in C._shards_userfills(vaults[:8], taille=5)] == [5, 3]
