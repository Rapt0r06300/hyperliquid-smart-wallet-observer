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
         "ts_ms": 1_000_000_000_000, "hash": "h1", "isSnapshot": False, "source": "LIVE_WS"}
    d.update(kw)
    return d


def test_ouvre_inline_sur_open_add_significatif(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"])   # 20×150 = 3000$ ≥ 2000
    assert r and r.get("ouverture") and r["ouverture"]["coin"] == "SOL"
    assert r["ouverture"]["prix_entree"] == 150.02 and r["paire"] == "SOL"                  # ask L2, clé paire = coin (ALPHA)
    assert r["latence_ws_open_ms"] is not None                                             # latence MONOTONE locale
    st = CO.statut(CO.ALPHA, tmp_path, now_ms=now)
    assert st["positions_ouvertes"] == 1 and st["cohorte"] == "ALPHA_PAPER" and st["real_execution"] is False


def test_raw_probe_ouvre_sans_edge_par_paire(tmp_path):
    """RAW_PROBE : ouvre sur tout OPEN/ADD candidat liquide SANS edge requis, clé PAR PAIRE vault+coin,
    mini 5 $, marquée NON_VALIDEE (sert à MESURER la paire)."""
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.RAW_PROBE, tmp_path)
    # DOGE n'est dans AUCUNE table prélim -> ALPHA/PROBE refuseraient. RAW ouvre quand même (liquide).
    fill = _fill(coin="DOGE", sz=2, px=150.0)                       # 2×150 = 300 ≥ seuil RAW 200
    r = CO.traiter_fill(CO.RAW_PROBE, etat, fill, tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"])
    assert r and r.get("ouverture")
    pos = r["ouverture"]
    assert pos["paire"] == "0xV|DOGE" and pos["notional_usd"] <= 5.0                        # clé paire + mini 5 $
    assert pos["meta"]["statut"] == "NON_VALIDEE" and pos["edge_estime_bps"] is None         # sans edge, non validée
    assert r["latence_ws_open_ms"] is not None
    # max 2 positions : une 2e paire ouvre, une 3e est refusée
    CO.traiter_fill(CO.RAW_PROBE, etat, _fill(coin="WLD", sz=2, px=150.0, hash="w"), tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"])
    r3 = CO.traiter_fill(CO.RAW_PROBE, etat, _fill(coin="LDO", sz=2, px=150.0, hash="l"), tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"])
    assert r3 and r3.get("refus") == "LIMITE_POSITIONS"


def test_agrege_plusieurs_petits_open(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(sz=7, hash="a"), tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"]) is None  # 1050 < 2000
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(sz=7, hash="b"), tmp_path, now_ms=now + 1000, lecteur_l2=_l2, token=etat["token"])      # cumul 2100
    assert r and r.get("ouverture")                                                        # agrégé -> ouvre


def test_refuse_sans_token_valide(tmp_path):
    """PROVENANCE HORS PAYLOAD : sans le token EN MÉMOIRE (créé par le collecteur), un fill fabriqué est
    REFUSÉ — impossible de le connaître depuis le payload."""
    _setup(tmp_path)
    etat = CO.etat_initial(CO.ALPHA, tmp_path, run_id="run-test")
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=1e12, lecteur_l2=_l2)["refus"] == "PROVENANCE_NON_AUTORISEE"  # sans token
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=1e12, lecteur_l2=_l2, token="faux")["refus"] == "PROVENANCE_NON_AUTORISEE"  # mauvais token
    # avec le bon token (celui de la cohorte en mémoire) -> ça passe
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=1e12, lecteur_l2=_l2, token=etat["token"]).get("ouverture")


def test_pytest_ne_peut_pas_ecrire_runtime(tmp_path, monkeypatch):
    """ISOLATION PROUVÉE : une racine MARQUÉE runtime, sans autorisation du collecteur, REFUSE toute
    écriture (aucun pytest ne peut polluer le vrai RUNTIME_ROOT)."""
    import pytest
    monkeypatch.setattr(CO, "_RUNTIME_AUTORISE", None)             # comme un pytest : jamais autorisé
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / CO.MARQUEUR_RUNTIME).write_text("runtime")         # cette racine EST un runtime marqué
    assert CO._ecriture_permise(tmp_path) is False
    with pytest.raises(PermissionError):
        CO._sauver(CO.ALPHA, tmp_path, {"cash": 300, "ouvertes": {}, "realise_total_usd": 0.0})
    # après autorisation (ce que SEUL le collecteur fait), l'écriture est permise
    CO.autoriser_runtime("tok")
    assert CO._ecriture_permise(tmp_path) is True


def test_run_id_et_provenance_dans_ledger(tmp_path):
    _setup(tmp_path)
    etat = CO.etat_initial(CO.ALPHA, tmp_path, run_id="run-abc123")
    CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=1e12, lecteur_l2=_l2, token=etat["token"])   # ouvre (LIVE_WS)
    import json as _j
    ligne = _j.loads((tmp_path / "runtime" / "data" / "exploratory_paper_ledger.jsonl").read_text().splitlines()[0])
    assert ligne["run_id"] == "run-abc123" and ligne["source"] == "LIVE_WS" and ligne["evt"] == "OPEN"


def test_dedup_snapshot_et_hash(tmp_path):
    _setup(tmp_path)
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(isSnapshot=True), tmp_path, lecteur_l2=_l2, token=etat["token"]) is None   # snapshot ignoré
    CO.traiter_fill(CO.ALPHA, etat, _fill(hash="x"), tmp_path, now_ms=1e12, lecteur_l2=_l2, token=etat["token"])
    assert CO.traiter_fill(CO.ALPHA, etat, _fill(hash="x"), tmp_path, now_ms=1e12, lecteur_l2=_l2, token=etat["token"]) is None  # hash déjà vu


def test_leader_close_sort_inline(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"])          # ouvre SOL
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(dir="Close Long", signe=-1, hash="c2"),
                        tmp_path, now_ms=now + 5000, lecteur_l2=_l2, token=etat["token"])                        # leader clôt (start absent)
    assert r and r.get("fermeture") and r["fermeture"]["raison"] == "LEADER_A_CLOS"
    assert CO.charger_store(CO.ALPHA, tmp_path)["ouvertes"] == {}


def test_reduce_proportionnel_close_total_flip(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    CO.traiter_fill(CO.ALPHA, etat, _fill(sz=20), tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"])   # ouvre SOL (leader long 20)
    notional0 = CO.charger_store(CO.ALPHA, tmp_path)["ouvertes"]["SOL"]["notional_usd"]
    # REDUCE : le leader vend 5 sur 20 (start=20) -> réduit la copie de 25 %
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(dir="Close Long", signe=-1, sz=5, start_position=20.0, hash="r1"),
                        tmp_path, now_ms=now + 1000, lecteur_l2=_l2, token=etat["token"])
    assert r["reduction"]["raison"] == "LEADER_A_REDUIT" and round(r["reduction"]["fraction"], 2) == 0.25
    notional1 = CO.charger_store(CO.ALPHA, tmp_path)["ouvertes"]["SOL"]["notional_usd"]
    assert notional1 < notional0                                    # copie réduite proportionnellement
    # CLOSE : le leader vend le reste (15 sur 15) -> ferme tout
    r2 = CO.traiter_fill(CO.ALPHA, etat, _fill(dir="Close Long", signe=-1, sz=15, start_position=15.0, hash="c1"),
                         tmp_path, now_ms=now + 2000, lecteur_l2=_l2, token=etat["token"])
    assert r2["fermeture"]["raison"] == "LEADER_A_CLOS" and CO.charger_store(CO.ALPHA, tmp_path)["ouvertes"] == {}


def test_flip_ferme_et_reamorce(tmp_path):
    _setup(tmp_path)
    now = 1_000_000_000_500.0
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    CO.traiter_fill(CO.ALPHA, etat, _fill(sz=20), tmp_path, now_ms=now, lecteur_l2=_l2, token=etat["token"])   # long 20
    # FLIP : le leader vend 30 (start=20) -> passe short 10 -> ferme la copie + réamorce l'agrégation
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(dir="Close Long", signe=-1, sz=30, start_position=20.0, hash="f1"),
                        tmp_path, now_ms=now + 1000, lecteur_l2=_l2, token=etat["token"])
    assert r["fermeture"]["raison"] == "LEADER_A_FLIP" and r.get("flip") is True
    assert ("0xV", "SOL") in etat["agg"] and etat["agg"][("0xV", "SOL")]["sens"] == -1   # résidu short réamorcé


def test_probe_exclut_les_coins_alpha(tmp_path):
    _setup(tmp_path)
    # SOL est dans ALPHA (gelé) ; on le met AUSSI dans la table PROBE -> il doit être EXCLU côté PROBE
    (tmp_path / "runtime" / "data" / "copy_prelim_probe.json").write_text(json.dumps(
        {"table": {"SOL": {"edge_brut_bps": 40.0, "horizon_ms": 3.6e6, "stop_bps": 40.0},
                   "DOT": {"edge_brut_bps": 40.0, "horizon_ms": 3.6e6, "stop_bps": 40.0}}}))
    tp = CO.charger_table(CO.PROBE, tmp_path)
    assert "SOL" not in tp and "DOT" in tp                          # anti-double-comptage : SOL réservé à ALPHA


def test_auto_kill_expectancy_negative(tmp_path):
    _setup(tmp_path)
    # 10 trades clôturés perdants -> cohorte inactive
    led = tmp_path / "runtime" / "data" / "exploratory_paper_ledger.jsonl"
    led.write_text("\n".join(json.dumps({"evt": "CLOSE", "realized_usd": -0.5}) for _ in range(10)))
    assert CO.cohorte_active(CO.ALPHA, tmp_path) is False
    etat = CO.etat_initial(CO.ALPHA, tmp_path)
    r = CO.traiter_fill(CO.ALPHA, etat, _fill(), tmp_path, now_ms=1e12, lecteur_l2=_l2, token=etat["token"])
    assert r and r.get("refus") == "COHORTE_EN_PAUSE_AUTO_KILL"


def test_isolation_alpha_probe(tmp_path):
    _setup(tmp_path)
    # PROBE trade un coin HORS ALPHA (DOT), ses propres fichiers -> pas de pollution croisée
    (tmp_path / "runtime" / "data" / "copy_prelim_probe.json").write_text(json.dumps(
        {"table": {"DOT": {"edge_brut_bps": 40.0, "horizon_ms": 3_600_000.0, "stop_bps": 40.0, "take_profit_bps": 60.0}}}))
    etat = CO.etat_initial(CO.PROBE, tmp_path)
    r = CO.traiter_fill(CO.PROBE, etat, _fill(coin="DOT", sz=5), tmp_path, now_ms=1e12, lecteur_l2=_l2, token=etat["token"])  # 750 ≥ 500
    assert r and r.get("ouverture") and r["ouverture"]["notional_usd"] <= 15.0              # notional PROBE tout petit
    assert not (tmp_path / "runtime" / "data" / "exploratory_paper_positions.json").exists()  # ALPHA intact