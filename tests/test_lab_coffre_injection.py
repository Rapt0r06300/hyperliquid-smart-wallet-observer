"""Test du chargement du tier LOCAL du coffre-fort pour la recherche du labo."""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.copy_vault_local_lab import _charger_tier_local  # noqa: E402


def _ecrire_shard(root: Path, famille: str, rows: list[dict], nom: str = "lot__x") -> str:
    rel = f"runtime/coffre_certifie/local/shards/{famille}/{nom}.jsonl.gz"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as h:
        for r in rows:
            h.write(json.dumps(r) + "\n")
    return rel


def _index(root: Path, entrees: list[dict]) -> None:
    coffre = root / "runtime" / "coffre_certifie"
    coffre.mkdir(parents=True, exist_ok=True)
    (coffre / "LOCAL_INDEX.json").write_text(json.dumps({"shards": entrees}), encoding="utf-8")


def _sha(root: Path, rel: str) -> str:
    return hashlib.sha256((root / rel).read_bytes()).hexdigest()


def test_charge_fills_causaux_tagues(tmp_path):
    root = tmp_path
    rows = [{"vault": "0xabc", "coin": "ETH", "px": 2000.0, "sz": 1.0, "signe": 1,
             "ts_ms": 1799999999000, "source": "LIVE_POLL", "isSnapshot": False,
             "observed_at_ms": 1799999999500} for _ in range(3)]
    rel = _ecrire_shard(root, "fills_forward", rows)
    _index(root, [{"famille": "fills_forward", "shard": rel, "sha256": _sha(root, rel)}])

    res = _charger_tier_local(root)
    assert res["statut"] == "OK" and res["fills_causaux"] == 3
    assert len(res["_fills"]) == 3 and all(r["provenance_tier"] == "LOCAL" for r in res["_fills"])
    # jamais de quality=SAFE -> ne peut pas etre "prouve"
    assert all(r.get("quality") != "SAFE" and r.get("source_quality_status") != "SAFE"
               for r in res["_fills"])


def test_rejette_sha_altere(tmp_path):
    root = tmp_path
    rel = _ecrire_shard(root, "fills_forward", [{"vault": "0x1", "coin": "ETH", "px": 1.0,
                        "sz": 1.0, "signe": 1, "ts_ms": 1, "source": "LIVE_POLL", "isSnapshot": False}])
    _index(root, [{"famille": "fills_forward", "shard": rel, "sha256": "0" * 64}])  # SHA faux
    res = _charger_tier_local(root)
    assert res["shards_rejetes"] == 1 and res["_fills"] == []


def test_absent_si_pas_de_coffre(tmp_path):
    assert _charger_tier_local(tmp_path)["statut"] == "ABSENT"


def test_classe_fills_books_bbo(tmp_path):
    root = tmp_path
    r_fill = _ecrire_shard(root, "fills_forward", [{"vault": "0x1", "coin": "ETH", "ts_ms": 10,
                           "source": "LIVE_POLL", "isSnapshot": False, "px": 1.0, "sz": 1.0, "signe": 1}])
    r_l2 = _ecrire_shard(root, "book_l2", [{"coin": "ETH", "received_at_ms": 20, "exchange_ts_ms": 10,
                         "bid": 1.0, "ask": 2.0, "bids5": [[1.0, 1.0]], "asks5": [[2.0, 1.0]]}])
    r_bbo = _ecrire_shard(root, "bbo", [{"coin": "ETH", "received_at_ms": 20, "exchange_ts_ms": 10,
                          "bid_px": 1.0, "ask_px": 2.0, "bid_sz": 1.0, "ask_sz": 1.0}])
    _index(root, [
        {"famille": "fills_forward", "shard": r_fill, "sha256": _sha(root, r_fill)},
        {"famille": "book_l2", "shard": r_l2, "sha256": _sha(root, r_l2)},
        {"famille": "bbo", "shard": r_bbo, "sha256": _sha(root, r_bbo)},
    ])
    res = _charger_tier_local(root)
    assert res["fills_causaux"] == 1 and res["carnets"] == 1 and res["bbo"] == 1
    assert len(res["_books"]) == 1 and len(res["_bbo"]) == 1


def test_snapshot_non_compte_comme_causal(tmp_path):
    root = tmp_path
    # un fill snapshot/liquidation : present mais PAS compte comme causal
    rel = _ecrire_shard(root, "fills_forward", [{"vault": "0x1", "coin": "ETH", "ts_ms": 10,
                        "source": "userFills.liquidation", "isSnapshot": None, "px": 1.0, "sz": 1.0, "signe": 1}])
    _index(root, [{"famille": "fills_forward", "shard": rel, "sha256": _sha(root, rel)}])
    res = _charger_tier_local(root)
    assert res["fills_causaux"] == 0 and len(res["_fills"]) == 1  # present mais non causal


def test_cotations_du_collecteur_bbo_adaptees_a_la_forme_du_labo(tmp_path):
    """Le BBO Hyperliquid du collecteur (bid/ask/ts_ex) sert au labo : memes grandeurs, autres noms."""
    root = tmp_path
    base = {"venue": "HL", "type_ligne": "QUOTE", "coin": "BTC", "bid": 100.0, "ask": 100.5,
            "bid_sz": 2.0, "ask_sz": 3.0, "recv_wall_ts_ms": 5_000, "ts_ex": 4_900.0}
    rows = [
        base,
        {**base, "recv_wall_ts_ms": 5_400, "ts_ex": 5_300.0},             # meme seconde : non retenue
        {**base, "recv_wall_ts_ms": 6_000, "ts_ex": 5_950.0, "bid": 101.0, "ask": 101.5},
        {**base, "recv_wall_ts_ms": 7_000, "ts_ex": 6_900.0, "bid": 102.0, "ask": 101.0},   # croise
        {**base, "recv_wall_ts_ms": 8_000, "ts_ex": 9_000.0},             # bourse apres reception
        {**base, "recv_wall_ts_ms": 9_000, "ts_ex": 8_900.0, "bid_sz": None},               # sans taille
        {**base, "venue": "BIN_TRADE", "type_ligne": "TRADE", "recv_wall_ts_ms": 10_000},   # autre venue
        {"venue": "HL", "type_ligne": "QUOTE", "coin": "ETH", "bid": True, "ask": 2.0,
         "bid_sz": 1.0, "ask_sz": 1.0, "recv_wall_ts_ms": 11_000, "ts_ex": 10_900.0},       # booleen
    ]
    rel = _ecrire_shard(root, "bbo", rows)
    _index(root, [{"famille": "bbo", "shard": rel, "sha256": _sha(root, rel)}])
    res = _charger_tier_local(root)
    assert res["bbo"] == 2 and res["bbo_adaptees"] == 2 and res["bbo_denses_non_retenues"] == 1
    premiere, seconde = res["_bbo"]
    assert premiere == {
        "schema_version": "hypersmart.copy_vault_bbo.v1", "coin": "BTC", "received_at_ms": 5_000,
        "exchange_ts_ms": 4_900, "bid_px": 100.0, "bid_sz": 2.0, "ask_px": 100.5, "ask_sz": 3.0,
        "source": "HYPERLIQUID_BBO_WS", "data_origin": "REAL_OBSERVED", "causal_observation": True,
        "provenance_tier": "LOCAL", "adapte_depuis": "bbo_tape"}
    assert (seconde["received_at_ms"], seconde["bid_px"]) == (6_000, 101.0)
    assert all(r.get("quality") != "SAFE" for r in res["_bbo"])          # jamais "prouvable"


# ------------------------------------------------------------------ adresses « archive » : au coffre, non rejouées

def _plan(root: Path, leaders: list[dict]) -> None:
    chemin = root / "runtime" / "data" / "copy_vault_besoins_collecte.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"leaders": leaders}), encoding="utf-8")


def _fill_local(vault: str, ts: int) -> dict:
    return {"vault": vault, "coin": "ETH", "px": 2000.0, "sz": 1.0, "signe": 1, "ts_ms": ts,
            "source": "LIVE_POLL", "isSnapshot": False, "observed_at_ms": ts + 500}


def test_les_robots_et_les_clones_classes_archive_ne_sont_pas_rejoues(tmp_path):
    from hl_observer.backtesting import copy_vault_tier_local as T

    lent, robot, clone, inconnu = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40, "0x" + "d" * 40
    rows = ([_fill_local(lent, 1_799_999_000_000 + i) for i in range(3)]
            + [_fill_local(robot.upper().replace("0X", "0x"), 1_799_999_100_000 + i) for i in range(50)]
            + [_fill_local(clone, 1_799_999_200_000 + i) for i in range(7)]
            + [_fill_local(inconnu, 1_799_999_300_000 + i) for i in range(2)])
    rel = _ecrire_shard(tmp_path, "fills_forward", rows)
    _index(tmp_path, [{"famille": "fills_forward", "shard": rel, "sha256": _sha(tmp_path, rel)}])
    # sans plan : rien n'est écarté sur la foi d'un classement qui n'existe pas
    sans = _charger_tier_local(tmp_path)
    assert len(sans["_fills"]) == 62 and sans["fills_archive_non_rejoues"] == 0 and sans["adresses_archive"] is None
    assert T.adresses_archivees(tmp_path) is None
    _plan(tmp_path, [
        {"unit": lent, "addresses": [lent, clone], "archetype": "DIRECTIONAL_SLOW", "cadence": "PRIORITAIRE"},
        {"unit": robot, "addresses": [robot], "archetype": "HFT", "cadence": "ARCHIVE"},
    ])
    assert T.adresses_archivees(tmp_path) == {robot, clone}        # le robot, et le clone de l'opérateur lent
    avec = _charger_tier_local(tmp_path)
    assert {r["vault"] for r in avec["_fills"]} == {lent, inconnu}  # l'opérateur lent et l'adresse non classée restent
    assert len(avec["_fills"]) == 5 and avec["fills_archive_non_rejoues"] == 57 and avec["adresses_archive"] == 2
    assert avec["fills_causaux"] == 5
    # plan illisible : comportement d'avant (tout est injecté), jamais un filtrage au hasard
    (tmp_path / "runtime" / "data" / "copy_vault_besoins_collecte.json").write_text("{pas du json", encoding="utf-8")
    assert len(_charger_tier_local(tmp_path)["_fills"]) == 62


def test_les_chaines_repetees_sont_partagees_sans_changer_une_seule_valeur(tmp_path):
    """Mémoire : un million de fills du même leader ne doit pas porter un million de copies de son adresse."""
    lent = "0x" + "a" * 40
    rows = [dict(_fill_local(lent, 1_799_999_000_000 + i), dir="Open Long", side="B", hash=f"0x{i:064x}",
                 source_id="hyperliquid_public_userfills_poll") for i in range(200)]
    rel = _ecrire_shard(tmp_path, "fills_forward", rows)
    _index(tmp_path, [{"famille": "fills_forward", "shard": rel, "sha256": _sha(tmp_path, rel)}])
    charges = _charger_tier_local(tmp_path)["_fills"]
    assert [{k: v for k, v in r.items() if k != "provenance_tier"} for r in charges] == rows     # valeurs intactes
    for champ in ("vault", "coin", "source", "dir", "side", "source_id"):
        assert len({id(r[champ]) for r in charges}) == 1, champ                                # une seule chaîne partagée
    assert len({id(r["hash"]) for r in charges}) == 200                                         # l'unique reste unique


def test_signaux_comptes_sans_etre_gardes_et_fills_archives_jamais_decodes(tmp_path, monkeypatch):
    from hl_observer.backtesting import copy_vault_tier_local as T

    lent, robot = "0x" + "a" * 40, "0x" + "b" * 40
    r_fills = _ecrire_shard(tmp_path, "fills_forward",
                            [_fill_local(lent, 1_799_999_000_000), *[_fill_local(robot, 1_799_999_100_000 + i) for i in range(40)]])
    signaux = [{"coin": "ETH", "ts_ms": 1_799_999_000_000 + i, "funding": 0.0001} for i in range(9)] + [
        {"coin": "ETH", "ts_ms": None}, {"coin": "ETH", "snapshot_ts_ms": 1_799_999_000_500}]
    r_ctx = _ecrire_shard(tmp_path, "asset_ctx", signaux, nom="lot__ctx")
    _index(tmp_path, [{"famille": "fills_forward", "shard": r_fills, "sha256": _sha(tmp_path, r_fills)},
                      {"famille": "asset_ctx", "shard": r_ctx, "sha256": _sha(tmp_path, r_ctx)}])
    _plan(tmp_path, [{"unit": robot, "addresses": [robot], "archetype": "HFT", "cadence": "ARCHIVE"}])
    gardes = _charger_tier_local(tmp_path)
    assert gardes["signaux_par_famille"] == {"asset_ctx": 10} and len(gardes["_signaux"]["asset_ctx"]) == 10
    # le labo principal : mêmes décomptes, aucune ligne de signal gardée en mémoire
    legers = _charger_tier_local(tmp_path, garder_signaux=False)
    assert legers["signaux_par_famille"] == {"asset_ctx": 10} and legers["signaux_total"] == 10
    assert legers["_signaux"] == {"asset_ctx": []}
    assert len(legers["_fills"]) == 1 and legers["fills_archive_non_rejoues"] == 40
    # les fills archivés ne passent jamais par le décodeur JSON
    decodes: list[str] = []
    reel = T.json.loads
    monkeypatch.setattr(T.json, "loads", lambda texte, *a, **k: (decodes.append(texte), reel(texte, *a, **k))[1])
    _charger_tier_local(tmp_path, garder_signaux=False)
    assert sum(robot in texte for texte in decodes if '"vault"' in texte) == 0
    assert sum(lent in texte for texte in decodes if '"vault"' in texte) == 1


def test_l_identite_de_connexion_survit_du_collecteur_au_moteur_en_passant_par_le_coffre(tmp_path):
    """Le labo lit le COFFRE, pas les fichiers bruts : la chaîne entière doit garder ce que le moteur exige.

    Cas réel du 2026-11-12 : 1,2 million de carnets au coffre sans identité de connexion, aucun trade
    exécutable. Collecteur -> certificateur (scelleur) -> coffre LOCAL -> pont du labo -> ruban -> moteur.
    """
    import asyncio

    sys.path.insert(0, str(RACINE / "tools"))
    import collecter_l2_lane as lane_module
    import sceller_coffre_local as scl

    from hl_observer.backtesting import copy_vault_executable as cv

    t0 = 1_800_000_600_000                                     # dix minutes après l'heure pile (funding)
    instants = (t0, t0 + 62_000, t0 + 363_000)                 # référence, entrée (+60 s), sortie (+300 s)
    data = tmp_path / "runtime" / "data"
    lane = lane_module.LaneL2(data / "copy_vault_l2_lane.jsonl", data / "copy_vault_bbo_lane.jsonl")

    def frame(coin, instant):
        return {"coin": coin, "time": instant, "levels": [
            [{"px": "2000.0", "sz": "5"}, {"px": "1999.0", "sz": "10"}],
            [{"px": "2001.0", "sz": "4"}, {"px": "2002.0", "sz": "8"}]]}

    async def collecter():
        for instant in instants:
            await lane.ecrire(lane_module.construire_carnet(frame("ETH", instant), recv_ms=instant + 50)[0], "cx-lane")
            await lane.ecrire_bbo(lane_module.construire_bbo(frame("SOL", instant), recv_ms=instant + 50)[0], "cx-lane")

    asyncio.run(collecter())
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(t0 + 400_000)]) == 0          # le Certificateur

    local = _charger_tier_local(tmp_path)                                                     # le pont du labo
    carnets_eth = [r for r in local["_books"] if r["coin"] == "ETH"]
    bbo_sol = [r for r in local["_bbo"] if r["coin"] == "SOL"]
    assert len(carnets_eth) == 3 and len(bbo_sol) == 3
    for row in carnets_eth:
        assert row["connection_id"] == "cx-lane" and row["l2_gap_epoch"] == 0 and row["capacity_usd"] > 0
        assert row["provenance_tier"] == "LOCAL"
    assert all(r["connection_id"] == "cx-lane" and r["l2_gap_epoch"] == 0 for r in bbo_sol)

    # le labo écrit ces lignes telles quelles dans son espace de travail, puis son chargeur les lit
    espace = tmp_path / "espace"
    (espace / "runtime" / "data").mkdir(parents=True)
    (espace / "runtime" / "data" / "copy_vault_l2_tape.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in local["_books"]), encoding="utf-8")
    (espace / "runtime" / "data" / "copy_vault_bbo_tape.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in local["_bbo"]), encoding="utf-8")
    carnets, audit = cv.load_observed_books(espace, coins={"ETH", "SOL"})
    assert audit["invalid_rows"] == 0 and len(carnets["ETH"]) == 3 and len(carnets["SOL"]) == 3

    def signal(coin):
        entree = {"event_id": "e-" + coin, "ts_ms": t0 + 1_000, "coin": coin, "direction": 1, "action": "ADD",
                  "dir": "Open Long", "vault": "0xA", "taille_usd": 100.0, "move_frac": 0.01, "source": "LIVE_WS",
                  "is_snapshot": False, "observed_at_ms": t0 + 1_025, "received_at_ms": t0 + 1_025}
        return cv.cluster_metaorders([entree])[0][0]

    trade, raison = cv.execute_metaorder(signal("ETH"), carnets["ETH"], horizon_ms=300_000, require_causal_books=True)
    assert raison == "LIQUIDATABLE_NET" and trade is not None            # carnets L2 du coffre : exécutables
    _trade, raison_bbo = cv.execute_metaorder(signal("SOL"), carnets["SOL"], horizon_ms=300_000,
                                              require_causal_books=True)
    assert raison_bbo not in {"L2_CONNECTION_IDENTITY_INCOMPLETE", "L2_GAP_EPOCH_IDENTITY_INCOMPLETE"}


def test_les_flux_autrefois_gaches_sont_maintenant_charges_comme_signaux(tmp_path):
    """2026-11-12 : leader_orders, funding_history, vault_ledger, vault_portfolio, micro_* étaient
    collectés + certifiés mais jamais chargés par le labo. Ils doivent maintenant être disponibles."""
    from hl_observer.backtesting import copy_vault_tier_local as T

    attendus = {"leader_orders", "funding_history", "vault_ledger", "vault_portfolio",
                "micro_bbo", "micro_l2", "micro_trades"}
    assert attendus <= T._COFFRE_FAMILLES_SIGNAUX                       # branchés comme signaux

    # un shard de chaque flux autrefois gâché est maintenant chargé et compté par le pont du labo
    entrees = []
    for i, famille in enumerate(sorted(attendus)):
        rel = _ecrire_shard(tmp_path, famille, [{"coin": "ETH", "ts_ms": 1_799_999_000_000 + i}], nom=f"lot__{famille}")
        entrees.append({"famille": famille, "shard": rel, "sha256": _sha(tmp_path, rel)})
    _index(tmp_path, entrees)
    # gardés : chaque famille apparaît dans _signaux ; comptés : chaque famille dans le décompte
    gardes = _charger_tier_local(tmp_path)
    assert attendus <= set(gardes["_signaux"]) and attendus <= set(gardes["signaux_par_famille"])
    assert all(gardes["signaux_par_famille"][f] == 1 for f in attendus)
    # labo principal (garder_signaux=False) : comptés sans être gardés (aucun coût mémoire)
    legers = _charger_tier_local(tmp_path, garder_signaux=False)
    assert attendus <= set(legers["signaux_par_famille"]) and all(legers["_signaux"][f] == [] for f in attendus)
