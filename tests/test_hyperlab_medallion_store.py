"""[Bloc 29-31] Persistance medaillon REELLE : Bronze immuable hashe, Silver/Gold Parquet partitionne."""
from hl_observer.hyperlab import medallion_store as ms


def _rows():
    return [
        {"ts": 1720000000000, "venue": "bybit", "symbole": "BTCUSDT", "type": "trade",
         "prix": "60000", "taille": "0.5", "side": "buy"},
        {"ts": 1720086400000, "venue": "bybit", "symbole": "ETHUSDT", "type": "trade",
         "prix": "3000", "taille": "2", "side": "sell"},
        {"ts": None, "venue": "bybit", "symbole": "XRPUSDT", "type": "trade",
         "prix": None, "taille": None, "side": None},
    ]


def test_bronze_immuable_hashe(tmp_path):
    root = str(tmp_path)
    out = ms.ecrire_bronze(root, "bybit", _rows())
    assert out["n"] == 3 and out["immutable"] and ms.verifier_bronze(out["path"])
    # contenu different -> hash/chemin different
    autres = _rows()[:2]
    out2 = ms.ecrire_bronze(root, "bybit", autres)
    assert out2["hash"] != out["hash"] and out2["path"] != out["path"]


def test_silver_partitionne_et_relu(tmp_path):
    root = str(tmp_path)
    res = ms.to_silver_parquet(root, "bybit", _rows())
    assert res["n"] == 3
    # deux dates connues + une 'unknown'
    assert "unknown" in res["dates"] and len([d for d in res["dates"] if d != "unknown"]) == 2
    relu = ms.relire_parquet(res["dir"])
    assert len(relu) == 3
    prix = sorted(r["prix"] for r in relu if r["prix"] is not None)
    assert prix == [3000.0, 60000.0]


def test_gold_notionnel_sans_faux_zero(tmp_path):
    root = str(tmp_path)
    g = ms.to_gold_parquet(root, _rows())
    relu = ms.relire_parquet(g["path"])
    notio = {r["symbole"]: r["notionnel"] for r in relu}
    assert notio["BTCUSDT"] == 30000.0 and notio["ETHUSDT"] == 6000.0
    assert notio["XRPUSDT"] is None   # entree manquante -> None, jamais 0
