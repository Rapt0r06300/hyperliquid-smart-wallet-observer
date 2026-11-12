"""Tests du collecteur L2 de lane (cœur pur construire_carnet, sans réseau)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import collecter_l2_lane as L  # noqa: E402

NOW = 1_800_000_000_000


def _frame(coin="ETH", exch=None, bids=None, asks=None):
    exch = exch if exch is not None else NOW - 100
    bids = bids or [{"px": "2000.0", "sz": "5"}, {"px": "1999.0", "sz": "10"}]
    asks = asks or [{"px": "2001.0", "sz": "4"}, {"px": "2002.0", "sz": "8"}]
    return {"coin": coin, "time": exch, "levels": [bids, asks]}


def test_carnet_valide():
    row, raison = L.construire_carnet(_frame(), recv_ms=NOW)
    assert row is not None and raison == ""
    assert row["coin"] == "ETH" and row["bid"] == 2000.0 and row["ask"] == 2001.0
    assert row["schema_version"] == "hypersmart.copy_vault_l2.v1"


def test_carnet_croise_rejete():
    row, raison = L.construire_carnet(
        _frame(bids=[{"px": "2002", "sz": "1"}], asks=[{"px": "2001", "sz": "1"}]), recv_ms=NOW)
    assert row is None and raison == "marche_croisee"


def test_carnet_niveaux_absents():
    row, raison = L.construire_carnet({"coin": "ETH", "time": NOW - 100, "levels": [[]]}, recv_ms=NOW)
    assert row is None


def test_carnet_lag_trop_grand_rejete():
    # exchange_ts tres ancien -> lag > 30s -> quarantaine
    row, raison = L.construire_carnet(_frame(exch=NOW - 10_000_000), recv_ms=NOW)
    assert row is None and raison in ("lag_causal_depasse", "timestamp_futur")


def test_charger_coins(tmp_path):
    cfg = tmp_path / "config" / "copy_vault_coins.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"coins": ["ETH", "BTC", "ETH", " SOL ", "kPEPE", "xyz:XYZ100", ""]}),
                   encoding="utf-8")
    coins = L._charger_coins(tmp_path, "config/copy_vault_coins.json")
    # Dédupliqué et débarrassé des espaces, MAIS identité native conservée : l'ancien passage en
    # majuscules abonnait la lane à « KPEPE » (inconnu de l'exchange), donc aucun carnet collecté.
    assert coins == ["ETH", "BTC", "SOL", "kPEPE", "xyz:XYZ100"]


def test_la_liste_reelle_des_lanes_garde_ses_symboles_sensibles_a_la_casse():
    """La liste commitée contient des coins « k… » : ils doivent arriver intacts à l'abonnement."""
    coins = L._charger_coins(RACINE, L.DEFAULT_COINS_FILE)
    natifs = json.loads((RACINE / L.DEFAULT_COINS_FILE).read_text(encoding="utf-8"))["coins"]
    assert coins == list(dict.fromkeys(str(c).strip() for c in natifs))
    sensibles = [c for c in natifs if c != c.upper()]
    assert sensibles and all(c in coins for c in sensibles)


def test_construire_bbo_valide():
    row, raison = L.construire_bbo(_frame(), recv_ms=NOW)
    assert row is not None and raison == ""
    assert row["schema_version"] == "hypersmart.copy_vault_bbo.v1"
    assert row["bid_px"] == 2000.0 and row["ask_px"] == 2001.0
    assert row["bid_sz"] == 5.0 and row["ask_sz"] == 4.0
    assert row["coin"] == "ETH" and row["source"] == "HYPERLIQUID_BBO_WS"


def test_construire_bbo_croise_rejete():
    row, raison = L.construire_bbo(
        _frame(bids=[{"px": "2002", "sz": "1"}], asks=[{"px": "2001", "sz": "1"}]), recv_ms=NOW)
    assert row is None and raison == "bbo_invalide_ou_croise"


def test_construire_bbo_lag_rejete():
    row, raison = L.construire_bbo(_frame(exch=NOW - 10_000_000), recv_ms=NOW)
    assert row is None and raison == "lag_causal_depasse"


def test_fusionner_carnets_dedup(tmp_path):
    import telecharger_l2_lanes_github as T
    root = tmp_path
    (root / "runtime" / "data").mkdir(parents=True)

    def _carnet(coin, exch):
        return {"schema_version": "hypersmart.copy_vault_l2.v1", "coin": coin,
                "received_at_ms": exch + 50, "exchange_ts_ms": exch,
                "bid": 2000.0, "ask": 2001.0,
                "bids5": [[2000.0, 5.0]], "asks5": [[2001.0, 4.0]],
                "source": "HYPERLIQUID_L2_WS"}

    art = root / "art"
    for sh in (0, 1):
        d = art / f"l2-shard-{sh}"
        d.mkdir(parents=True)
        rows = [_carnet("ETH", NOW - 1000 + sh), _carnet("ETH", NOW - 1000 + sh)]  # doublon interne
        (d / "copy_vault_l2_lane.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    rap = T.fusionner_carnets(root, art, now_ms=NOW)
    # 2 instants distincts (NOW-1000 et NOW-999), doublons retirés
    assert rap["total_final"] == 2
    cible = root / "runtime" / "data" / "copy_vault_l2_tape.jsonl"
    assert cible.exists() and len(cible.read_text().splitlines()) == 2


def test_fusionner_bbo_dedup(tmp_path):
    import telecharger_l2_lanes_github as T
    root = tmp_path
    (root / "runtime" / "data").mkdir(parents=True)

    def _bbo(exch):
        return {"schema_version": "hypersmart.copy_vault_bbo.v1", "coin": "ETH",
                "received_at_ms": exch + 50, "exchange_ts_ms": exch,
                "bid_px": 2000.0, "bid_sz": 5.0, "ask_px": 2001.0, "ask_sz": 4.0,
                "source": "HYPERLIQUID_BBO_WS"}

    art = root / "art"
    d = art / "l2-shard-0"
    d.mkdir(parents=True)
    rows = [_bbo(NOW - 1000), _bbo(NOW - 1000), _bbo(NOW - 500)]  # 1 doublon
    (d / "copy_vault_bbo_lane.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    rap = T.fusionner_bbo(root, art, now_ms=NOW)
    assert rap["total_final"] == 2  # 2 instants distincts
    cible = root / "runtime" / "data" / "copy_vault_bbo_tape.jsonl"
    assert cible.exists() and len(cible.read_text().splitlines()) == 2


def test_chaque_carnet_porte_l_identite_de_sa_connexion_et_l_epoque_de_son_marche(tmp_path):
    """Cas réel du 2026-11-12 : 1,2 million de carnets collectés sans identité, aucun trade exécutable."""
    import asyncio

    lane = L.LaneL2(tmp_path / "l2.jsonl", tmp_path / "bbo.jsonl")

    async def scenario():
        for i in range(2):
            frame = _frame("kPEPE", exch=NOW - 1_000 + i)
            await lane.ecrire_bbo(L.construire_bbo(frame, recv_ms=NOW)[0], "cx-1")
            await lane.ecrire(L.construire_carnet(frame, recv_ms=NOW)[0], "cx-1")
        lane.incident(["kPEPE"])                                   # trame rejetée pour ce marché
        await lane.ecrire(L.construire_carnet(_frame("kPEPE", exch=NOW - 500), recv_ms=NOW)[0], "cx-1")
        lane.incident(["kPEPE", "ETH"])                            # déconnexion : tous les marchés du socket
        await lane.ecrire(L.construire_carnet(_frame("kPEPE", exch=NOW - 400), recv_ms=NOW)[0], "cx-2")
        await lane.ecrire(L.construire_carnet(_frame("ETH", exch=NOW - 400), recv_ms=NOW)[0], "cx-2")
        await lane.ecrire(L.construire_carnet(_frame("SOL", exch=NOW - 400), recv_ms=NOW)[0])   # ancien appel

    asyncio.run(scenario())
    l2 = [json.loads(x) for x in (tmp_path / "l2.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["coin"], r.get("connection_id"), r.get("l2_gap_epoch")) for r in l2] == [
        ("kPEPE", "cx-1", 0), ("kPEPE", "cx-1", 0), ("kPEPE", "cx-1", 1), ("kPEPE", "cx-2", 2), ("ETH", "cx-2", 1),
        ("SOL", None, None)]
    bbo = [json.loads(x) for x in (tmp_path / "bbo.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["connection_id"], r["l2_gap_epoch"]) for r in bbo] == [("cx-1", 0), ("cx-1", 0)]
    # un marché calme (aucune trame pendant plus de GAP_L2_MS) reste un diagnostic, pas un changement d'époque
    assert lane.epoque == {"KPEPE": 2, "ETH": 1}


def test_un_trade_n_est_executable_que_sur_des_carnets_de_la_meme_connexion(tmp_path):
    """Bout en bout : collecteur -> certificateur -> ruban -> chargeur du labo -> moteur d'exécution."""
    import asyncio

    from hl_observer.backtesting import copy_vault_executable as cv
    from hl_observer.datasets.coffre_certifie import certifier_book

    t0 = NOW + 600_000                                             # dix minutes après l'heure pile (funding)
    instants = (t0, t0 + 62_000, t0 + 363_000)                     # référence, entrée (+60 s), sortie (+300 s)
    entree = {"event_id": "e1", "ts_ms": t0 + 1_000, "coin": "ETH", "direction": 1, "action": "ADD",
              "dir": "Open Long", "vault": "0xA", "taille_usd": 100.0, "move_frac": 0.01, "source": "LIVE_WS",
              "is_snapshot": False, "observed_at_ms": t0 + 1_025, "received_at_ms": t0 + 1_025}
    metaordre = cv.cluster_metaorders([entree])[0][0]

    def rejouer(identites):
        racine = tmp_path / ("cas_%d" % len(list(tmp_path.iterdir())))
        ruban = racine / "runtime" / "data" / "copy_vault_l2_tape.jsonl"
        lane = L.LaneL2(ruban, racine / "bbo.jsonl")

        async def ecrire():
            for instant, (connexion, epoque) in zip(instants, identites, strict=True):
                lane.epoque["ETH"] = epoque
                row, raison = L.construire_carnet(_frame("ETH", exch=instant), recv_ms=instant + 50)
                assert raison == ""
                certifie, _decision, _motif = certifier_book(row, source="HYPERLIQUID_L2_WS", now_ms=instant + 50)
                await lane.ecrire(certifie, connexion)

        asyncio.run(ecrire())
        carnets, _audit = cv.load_observed_books(racine, coins={"ETH"})
        return cv.execute_metaorder(metaordre, carnets.get("ETH", []), horizon_ms=300_000, require_causal_books=True)

    trade, raison = rejouer([("cx", 0)] * 3)
    assert raison == "LIQUIDATABLE_NET" and trade is not None and trade["book_binding_method"] == "CONTINUOUS_CAUSAL_BOOK"
    assert rejouer([(None, 0)] * 3) == (None, "L2_CONNECTION_IDENTITY_INCOMPLETE")       # l'ancien collecteur
    assert rejouer([("cx", 0), ("cx", 0), ("autre", 0)]) == (None, "L2_CONNECTION_GAP_CROSSED")
    assert rejouer([("cx", 0), ("cx", 0), ("cx", 1)]) == (None, "L2_GAP_EPOCH_CROSSED")


def test_un_carnet_bbo_de_lane_garde_son_identite_jusqu_au_moteur(tmp_path):
    """Le repli BBO du labo perdait l'identité de connexion : aucun trade ne pouvait s'exécuter dessus."""
    import asyncio

    from hl_observer.backtesting import copy_vault_executable as cv
    from hl_observer.datasets.coffre_certifie import certifier_bbo

    t0 = NOW + 600_000
    lane = L.LaneL2(tmp_path / "l2.jsonl", tmp_path / "runtime" / "data" / "copy_vault_bbo_tape.jsonl")

    async def ecrire():
        for instant in (t0, t0 + 62_000, t0 + 363_000):
            bbo, raison = L.construire_bbo(_frame("ETH", exch=instant), recv_ms=instant + 50)
            assert raison == ""
            certifie, _decision, _motif = certifier_bbo(bbo, source="HYPERLIQUID_BBO_WS", now_ms=instant + 50)
            await lane.ecrire_bbo(certifie, "cx-bbo")

    asyncio.run(ecrire())
    carnets, _audit = cv.load_observed_books(tmp_path, coins={"ETH"})
    assert [(r["connection_id"], r["l2_gap_epoch"]) for r in carnets["ETH"]] == [("cx-bbo", 0)] * 3
    entree = {"event_id": "e1", "ts_ms": t0 + 1_000, "coin": "ETH", "direction": 1, "action": "ADD",
              "dir": "Open Long", "vault": "0xA", "taille_usd": 100.0, "move_frac": 0.01, "source": "LIVE_WS",
              "is_snapshot": False, "observed_at_ms": t0 + 1_025, "received_at_ms": t0 + 1_025}
    metaordre = cv.cluster_metaorders([entree])[0][0]
    _trade, raison = cv.execute_metaorder(metaordre, carnets["ETH"], horizon_ms=300_000, require_causal_books=True)
    assert raison not in {"L2_CONNECTION_IDENTITY_INCOMPLETE", "L2_GAP_EPOCH_IDENTITY_INCOMPLETE"}
