"""Moteur INLINE deux-cohortes (rectif Flo 23/07) : le fill WS ouvre dans le même flux. On prouve :
agrégation OPEN/ADD en $, admission→L2→open inline avec latence, dédup isSnapshot/hash, sortie sur
REDUCE/CLOSE du leader, auto-KILL sur expectancy live négative, isolation ALPHA/PROBE. Aucun réseau."""
from __future__ import annotations

import json

from hl_observer.experimental import cohortes as CO


def _setup(root):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "frais_venues.json").write_text(json.dumps({"hl_taker_bps": 3.5, "bin_taker_bps": 4.5}))
    (root / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "retenus": ["0xV"], "classement": [{"vault": "0xV", "retenu": True, "facteurs": {}}]}))
    (root / "runtime" / "data" / "copy_prelim_gele_v1.json").write_text(json.dumps(
        {"table": {"SOL": {"edge_brut_bps": 35.0, "net_bps": 23.0, "horizon_ms": 3_600_000.0,
                           "stop_bps": 35.0, "take_profit_bps": 54.0}}}))


def _l2(coin):
    return {"hl_bid": 149.98, "hl_ask": 150.02, "depth_usd": 5000.0, "age_ms": 50}


def _fill(**kw):
    d = {"vault": "0xV", "coin": "SOL", "px": 150.0, "sz": 20.0, "signe": 1, "dir": "Open Long",
         "ts_ms": 1_000_000_000_000, "hash": "h1", "isSnapshot": False}
    d.update(kw)
    return d


def test_ouvre_inline_sur_open_add_significatif(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=now, lecteur_l2=_l2)   # 20×150 = 3000$ ≥ 2000
    assert r and r.get("ouverture") and r["ouverture"]["coin"] == "SOL"
    assert r["ouverture"]["prix_entree"] == 150.02 and r["latence_ms"] == 500              # ask L2, latence fill→copie
    st = CO.statut(CO.ALPHA, tmp_path, now_ms=now)
    assert st["positions_ouvertes"] == 1 and st["cohorte"] == "ALPHA_PAPER" and st["real_execution"] is False


def test_agrege_plusieurs_petits_open(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(sz=7, hash="a"), tmp_path, now_ms=now, lecteur_l2=_l2) is None  # 1050 < 2000
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(sz=7, hash="b"), tmp_path, now_ms=now + 1000, lecteur_l2=_l2)      # cumul 2100
    assert r and r.get("ouverture")                                                        # agrégé -> ouvre


def test_dedup_snapshot_et_hash(tmp_path):
    _setup(tmp_path)
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(isSnapshot=True), tmp_path, lecteur_l2=_l2) is None   # snapshot ignoré
    CO.traiter_fill(CO.ALPHA, etat, _fill(hash="x"), tmp_path, now_ms=1e12, lecteur_l2=_l2)
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(hash="x"), tmp_path, now_ms=1e12, lecteur_l2=_l2) is None  # hash déjà vu


def test_leader_close_sort_inline(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=now, lecteur_l2=_l2)          # ouvre SOL
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(dir="Close Long", signe=-1, hash="c2"),
                        tmp_path, now_ms=now + 5000, lecteur_l2=_l2)                        # leader clôt
    assert r and r.get("fermeture") and r["fermeture"]["raison"] == "LEADER_A_REDUIT"
    assert CO.charger_store(CO.ALPHA, tmp_path)["ouvertes"] == {}


def test_auto_kill_expectancy_negative(tmp_path):
    _setup(tmp_path)
    # 10 trades clôturés perdants -> cohorte inactive
    led = tmp_path / "runtime" / "data" / "exploratory_paper_ledger.jsonl"
    led.write_text("\n".join(json.dumps({"evt": "CLOSE", "realized_usd": -0.5}) for _ in range(10)))
    assert CO.cohorte_active(CO.ALPHA, tmp_path) is False
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=1e12, lecteur_l2=_l2)
    assert r and r.get("refus") == "COHORTE_EN_PAUSE_AUTO_KILL"


def test_isolation_alpha_probe(tmp_path):
    _setup(tmp_path)
    # PROBE utilise sa propre table + ses propres fichiers -> pas de pollution croisée
    (tmp_path / "runtime" / "data" / "copy_prelim_probe.json").write_text(json.dumps(
        {"table": {"SOL": {"edge_brut_bps": 40.0, "horizon_ms": 3_600_000.0, "stop_bps": 40.0, "take_profit_bps": 60.0}}}))
    etat = CO.etat_initial(CO.PROBE, tmp_path)
    r = CO.traiter_fill(CO.PROBE, etat, _fill(sz=5), tmp_path, now_ms=1e12, lecteur_l2=_l2)  # 5×150=750 ≥ 500 (PROBE)
    assert r and r.get("ouverture") and r["ouverture"]["notional_usd"] <= 15.0              # notional PROBE tout petit
    assert not (tmp_path / "runtime" / "data" / "exploratory_paper_positions.json").exists()  # ALPHA intact