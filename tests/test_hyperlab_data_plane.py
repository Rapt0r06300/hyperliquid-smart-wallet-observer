"""[Bloc 37] E2E data plane : producteur -> Bronze -> Silver -> Gold -> catalogue, sur lot reel persiste,
puis construction PreuveLive -> gate LIVE_READY (not ready sans preuve runtime, ready avec)."""
import os

from hl_observer.hyperlab import data_plane as dp
from hl_observer.hyperlab import data_mesh_catalog as dm
from hl_observer.hyperlab import live_ready as lr


def _records():
    return [
        {"ts": 1720000000000, "venue": "bybit", "symbole": "BTCUSDT", "type": "trade",
         "prix": "60000", "taille": "0.5", "side": "buy"},
        {"ts": 1720000001000, "venue": "bybit", "symbole": "BTCUSDT", "type": "trade",
         "prix": "60010", "taille": "1", "side": "sell"},
    ]


def test_chaine_bronze_silver_gold_catalogue(tmp_path):
    root = str(tmp_path / "lake")
    conn = dm.ouvrir(str(tmp_path / "mesh.db"))
    dm.bootstrap(conn, ts=1000.0)
    ing = dp.ingerer(root, conn, "bybit", _records(), ts=1000.0)
    assert ing["lineage"] == ["bronze", "silver", "gold", "catalogue"]
    # 3 etages persistes ET catalogues
    etages = {d["etage"] for d in ing["catalogue"]}
    assert etages == {"bronze", "silver", "gold"}
    # relecture reelle des artefacts
    from hl_observer.hyperlab import medallion_store as ms
    assert ms.verifier_bronze(ing["bronze"]["path"])
    gold = ms.relire_parquet(ing["gold"]["path"])
    notio = {r["symbole"]: r["notionnel"] for r in gold}
    assert notio["BTCUSDT"] == 60010.0   # dernier lot : 60010*1 (les deux BTCUSDT presents)
    silver = ms.relire_parquet(ing["silver"]["dir"])
    assert len(silver) == 2


def test_ingest_alimente_stockage_mais_pas_le_live(tmp_path):
    root = str(tmp_path / "lake")
    conn = dm.ouvrir(str(tmp_path / "mesh.db"))
    dm.bootstrap(conn, ts=1000.0)
    ing = dp.ingerer(root, conn, "bybit", _records(), ts=1000.0)
    # meme avec du stockage reel, SANS connexion/messages/fraicheur/sequences/replay -> pas live
    p = dp.preuve_live_depuis_ingest("bybit", ing, connexion=False, n_messages=0,
                                     last_useful_event_ts=None, sequences_ok=False, replay_parite=False)
    r = lr.evaluer_live_ready(p, maintenant=2000.0, seuil_fraicheur_s=60)
    assert r["live_ready"] is False and "stockage" not in r["manquants"]  # stockage OK, le reste manque
    # avec toutes les preuves runtime -> live ready
    p2 = dp.preuve_live_depuis_ingest("bybit", ing, connexion=True, n_messages=5,
                                      last_useful_event_ts=1990.0, sequences_ok=True, replay_parite=True)
    assert lr.evaluer_live_ready(p2, maintenant=2000.0, seuil_fraicheur_s=60)["live_ready"] is True
