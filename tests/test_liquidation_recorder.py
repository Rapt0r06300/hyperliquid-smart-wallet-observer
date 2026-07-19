"""X-11 — l'enregistreur de la carte : ecrit ce qu'on VOIT, refuse ce qu'il ne comprend pas,
et son resume dit AUCUN_HISTORIQUE au lieu d'inventer."""
from __future__ import annotations

from hl_observer.market.liquidation_map import Grappe
from hl_observer.market.liquidation_recorder import (
    enregistrer_grappes, resume_historique, rows_depuis_grappes,
)


def _g(coin="BTC", prix=60000.0, sens="SELL", notionnel=25_000.0, n=3, dist=120.0):
    return Grappe(coin=coin, prix=prix, sens=sens, notionnel_usd=notionnel,
                  n_wallets=n, distance_bps=dist)


def test_rows_purs_ecarte_l_illisible():
    rows = rows_depuis_grappes([
        _g(), {"coin": "ETH", "prix": 3000.0, "sens": "BUY", "notionnel_usd": 12_000.0,
               "n_wallets": 2, "distance_bps": 80.0},
        {"coin": "", "prix": 1.0, "sens": "SELL", "notionnel_usd": 1.0, "n_wallets": 1, "distance_bps": 1.0},
        {"coin": "SOL", "prix": -5, "sens": "SELL", "notionnel_usd": 1.0, "n_wallets": 1, "distance_bps": 1.0},
        {"coin": "DOGE", "prix": 0.1, "sens": "N_IMPORTE_QUOI", "notionnel_usd": 1.0, "n_wallets": 1, "distance_bps": 1.0},
    ], ts_ms=123, session_id="S-T")
    assert len(rows) == 2                       # BTC + ETH ; les 3 illisibles ECARTES
    assert rows[0][0] == 123 and rows[0][1] == "S-T"


def test_enregistrer_puis_resume(tmp_path):
    db = tmp_path / "liq.sqlite3"
    n = enregistrer_grappes([_g(), _g(coin="ETH", prix=3000.0, sens="BUY")],
                            ts_ms=1_000, session_id="S-T", db_path=db)
    assert n == 2
    n2 = enregistrer_grappes([_g(prix=60100.0)], ts_ms=3_601_000, session_id="S-T", db_path=db)
    assert n2 == 1
    r = resume_historique(db_path=db)
    assert r["snapshots"] == 3 and r["coins"] == 2
    assert r["heures_couvertes"] == 1.0
    assert r["verdict"] == "HISTORIQUE_EN_CONSTITUTION"
    assert r["real_execution"] is False


def test_resume_sans_historique_dit_impossible(tmp_path):
    r = resume_historique(db_path=tmp_path / "absent.sqlite3")
    assert r["snapshots"] == 0
    assert r["verdict"] == "AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE"


def test_enregistrer_zero_grappe_ne_cree_rien(tmp_path):
    db = tmp_path / "liq.sqlite3"
    assert enregistrer_grappes([], ts_ms=1, session_id="", db_path=db) == 0
    assert not db.exists()                       # pas de base vide fantome
