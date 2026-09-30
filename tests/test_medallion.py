from hl_observer.research.medallion import bronze_immuable, to_silver, to_gold


def test_bronze_immuable_hash():
    a = bronze_immuable([{"px": 1}])
    assert a["immutable"] is True and a["hash"] != bronze_immuable([{"px": 2}])["hash"]


def test_to_silver_canonique_sans_invention():
    brute = {"p": 100.0, "q": 2.0, "s": "buy", "T": 1234}
    m = {"prix": "p", "taille": "q", "side": "s", "ts": "T"}
    s = to_silver(brute, m, venue="binance")
    assert s["prix"] == 100.0 and s["taille"] == 2.0 and s["venue"] == "binance"
    assert s["symbole"] is None                                  # non mappe -> None, pas invente


def test_to_gold_notionnel():
    silver = [{"ts": 1, "symbole": "BTC", "prix": 100.0, "taille": 2.0},
              {"ts": 2, "symbole": "BTC", "prix": None, "taille": 2.0}]
    g = to_gold(silver)
    assert g["features"][0]["notionnel"] == 200.0 and g["features"][1]["notionnel"] is None
