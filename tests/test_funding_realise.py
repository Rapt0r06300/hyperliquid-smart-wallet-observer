"""Le funding d'un episode se MESURE ou se DIT inconnu — jamais un zéro favorable.

POURQUOI CES TESTS EXISTENT. Mesure du 19/11/2026 : la porte `FUNDING_PNL_UNMEASURABLE` refusait
**100 % des 11 391 essais** du labo, parce que son seul statut acceptant était « aucun règlement
traversé » — impossible avec un règlement horaire et des horizons allant jusqu'à une heure. Le
statut `MEASURED` était accepté ailleurs dans le moteur, mais aucune ligne du dépôt ne le
produisait. La grandeur n'était pas non mesurable : elle n'était pas mesurée.

Ce que ces tests verrouillent :

  * le SIGNE, parce que s'en tromper transforme un coût en revenu : à taux positif, un long paie ;
  * la BORNE des règlements traversés, `(entrée, sortie]` : glisser d'un règlement change le coût
    sans que rien ne le dise ;
  * le REFUS quand la série ne couvre pas l'épisode, au lieu d'un zéro qui flatterait le résultat ;
  * le verdict d'ensemble : une seule inconnue emporte le total, sinon il serait calculé sur les
    seuls épisodes lisibles — d'autant plus favorable qu'il en manque.
"""
from __future__ import annotations

from decimal import Decimal

from hl_observer.backtesting import copy_vault_funding_realise as fr

#: Trois règlements horaires, taux positif constant.
SERIE = [(3_600_000, Decimal("0.0001")),
         (7_200_000, Decimal("0.0001")),
         (10_800_000, Decimal("0.0001"))]
TAUX = {"BTC": SERIE}
#: La fenetre REELLEMENT lue : c'est elle qui dit ce qu'on sait, pas la position des
#: reglements. Un episode qui tient entre deux reglements n'en traverse aucun -- son funding
#: vaut zero, et c'est une mesure.
COUVERTURE = (0, 14_400_000)


def _trade(entree: int, sortie: int, *, direction: int = 1, notionnel: float = 100.0) -> dict:
    return {"coin": "BTC", "entry_ts_ms": entree, "exit_ts_ms": sortie,
            "direction": direction, "notional_usd": notionnel}


def test_un_long_paie_le_funding_quand_le_taux_est_positif() -> None:
    """Convention Hyperliquid : à taux positif, les longs paient les courts."""
    recu = fr.funding_du_trade(_trade(3_000_000, 8_000_000), TAUX, couverture_ms=COUVERTURE)
    assert recu["status"] == "MEASURED"
    assert recu["settlement_crossing_count"] == 2, "les règlements de 1 h et 2 h sont traversés"
    # 2 règlements x 0,0001 x 100 USD = 0,02 USD payés -> le résultat DIMINUE.
    assert recu["carry_pnl_usd"] < 0
    assert Decimal(recu["carry_pnl_usd_exact_decimal"]) == Decimal("-0.02")


def test_un_short_recoit_le_funding_quand_le_taux_est_positif() -> None:
    """Le signe inverse, sinon un coût deviendrait un revenu — le faux PnL que le contrat refuse."""
    recu = fr.funding_du_trade(_trade(3_000_000, 8_000_000, direction=-1), TAUX,
                                couverture_ms=COUVERTURE)
    assert recu["status"] == "MEASURED"
    assert Decimal(recu["carry_pnl_usd_exact_decimal"]) == Decimal("0.02")


def test_la_borne_des_reglements_traverses_est_verrouillee() -> None:
    """`(entrée, sortie]` : un règlement à l'instant de l'entrée n'est pas payé, celui de la
    sortie l'est — on détient encore la position au moment où il tombe."""
    pile_a_l_entree = fr.funding_du_trade(_trade(3_600_000, 7_000_000), TAUX, couverture_ms=COUVERTURE)
    assert pile_a_l_entree["settlement_crossing_count"] == 0, (
        "un règlement a l'instant exact de l'entrée n'est pas paye par la position qui s'ouvre"
    )
    assert Decimal(pile_a_l_entree["carry_pnl_usd_exact_decimal"]) == Decimal("0")

    pile_a_la_sortie = fr.funding_du_trade(_trade(3_000_000, 3_600_000), TAUX, couverture_ms=COUVERTURE)
    assert pile_a_la_sortie["settlement_crossing_count"] == 1, (
        "celui de la sortie est paye : la position est encore detenue quand il tombe"
    )


def test_un_episode_hors_couverture_est_refuse_et_non_mis_a_zero() -> None:
    """Supposer zéro là où on ne voit rien, c'est le zéro favorable que le contrat interdit."""
    avant = fr.funding_du_trade(_trade(1_000, 2_000_000), TAUX,
                                couverture_ms=(1_800_000, 14_400_000))
    assert avant["status"] == "UNMEASURABLE"
    assert avant["reason"] == "FUNDING_RATES_DO_NOT_COVER_EPISODE"
    assert avant["carry_pnl_usd"] is None, "aucun chiffre, surtout pas un zéro"

    apres = fr.funding_du_trade(_trade(5_000_000, 99_000_000), TAUX,
                                couverture_ms=COUVERTURE)
    assert apres["status"] == "UNMEASURABLE"
    assert apres["reason"] == "FUNDING_RATES_DO_NOT_COVER_EPISODE"


def test_un_coin_sans_taux_se_dit() -> None:
    recu = fr.funding_du_trade({**_trade(4_000_000, 8_000_000), "coin": "INCONNU"}, TAUX,
                               couverture_ms=COUVERTURE)
    assert recu["status"] == "UNMEASURABLE"
    assert recu["reason"] == "FUNDING_RATES_MISSING_FOR_COIN"


def test_les_champs_illisibles_se_disent_un_par_un() -> None:
    """Chaque manque a sa raison : « inconnu » sans motif ne se corrige pas."""
    cas = [
        ({"coin": "BTC", "entry_ts_ms": 4_000_000, "exit_ts_ms": 3_000_000,
          "direction": 1, "notional_usd": 100.0}, "FUNDING_TRADE_TIMESTAMPS_UNMEASURABLE"),
        ({"coin": "BTC", "entry_ts_ms": 4_000_000, "exit_ts_ms": 8_000_000,
          "direction": 1, "notional_usd": None}, "FUNDING_NOTIONAL_UNMEASURABLE"),
        ({"coin": "BTC", "entry_ts_ms": 4_000_000, "exit_ts_ms": 8_000_000,
          "direction": 0, "notional_usd": 100.0}, "FUNDING_DIRECTION_UNMEASURABLE"),
        ({"coin": "BTC", "entry_ts_ms": True, "exit_ts_ms": 8_000_000,
          "direction": 1, "notional_usd": 100.0}, "FUNDING_TRADE_TIMESTAMPS_UNMEASURABLE"),
    ]
    for trade, attendu in cas:
        assert fr.funding_du_trade(trade, TAUX, couverture_ms=COUVERTURE)["reason"] == attendu


def test_une_seule_inconnue_emporte_le_total() -> None:
    """Un total calculé sur les seuls épisodes lisibles est d'autant plus flatteur qu'il en manque."""
    lisible = _trade(3_000_000, 8_000_000)
    inconnu = {**_trade(3_000_000, 8_000_000), "coin": "INCONNU"}

    tous_lisibles = fr.funding_des_trades([lisible, lisible], TAUX, couverture_ms=COUVERTURE)
    assert tous_lisibles["status"] == "MEASURED"
    assert Decimal(tous_lisibles["carry_pnl_usd_exact_decimal"]) == Decimal("-0.04")
    assert tous_lisibles["settlement_crossing_count"] == 4

    melange = fr.funding_des_trades([lisible, inconnu], TAUX, couverture_ms=COUVERTURE)
    assert melange["status"] == "UNMEASURABLE"
    assert melange["carry_pnl_usd"] is None
    assert melange["measured_count"] == 1
    assert melange["reasons"] == {"FUNDING_RATES_MISSING_FOR_COIN": 1}


def test_la_provenance_est_dite_dans_chaque_recu() -> None:
    """Les taux viennent d'un rattrapage REST : un coût reconstitué ne doit pas passer pour une
    observation directe. Ils ne servent qu'à chiffrer APRÈS coup, jamais à décider."""
    for recu in (fr.funding_du_trade(_trade(3_000_000, 8_000_000), TAUX,
                                     couverture_ms=COUVERTURE),
                 fr.funding_du_trade(_trade(1, 2), TAUX, couverture_ms=COUVERTURE),
                 fr.funding_des_trades([_trade(3_000_000, 8_000_000)], TAUX,
                                       couverture_ms=COUVERTURE)):
        assert recu["provenance"] == fr.PROVENANCE_RECONSTITUEE


def test_un_intervalle_inattendu_est_refuse_et_compte(tmp_path, monkeypatch) -> None:
    """Un règlement toutes les 8 h au lieu d'1 h diviserait le coût par huit, silencieusement."""
    import json

    from hl_observer.backtesting import coffre_tranches

    (tmp_path / "runtime/coffre_certifie").mkdir(parents=True)
    (tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json").write_text(
        json.dumps({"shards": [{"famille": "funding_history", "shard": "s1",
                                "ts_min_ms": 0, "ts_max_ms": 99_000_000}]}), encoding="utf-8")
    lignes = [
        {"coin": "BTC", "ts_ms": 3_600_000, "funding": "0.0001", "interval": "1h"},
        {"coin": "BTC", "ts_ms": 7_200_000, "funding": "0.0001", "interval": "8h"},
        {"coin": "BTC", "ts_ms": 10_800_000, "funding": "pas-un-nombre", "interval": "1h"},
    ]
    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"shard": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter(lignes))

    taux, audit = fr.taux_du_coffre(tmp_path, coins=["BTC"], debut_ms=0, fin_ms=99_000_000)
    assert audit["reglements_gardes"] == 1
    assert audit["ecartes_intervalle_inattendu"] == 1
    assert audit["ecartes_taux_illisible"] == 1
    assert [instant for instant, _ in taux["BTC"]] == [3_600_000]


def test_le_coffre_absent_se_dit(tmp_path) -> None:
    """« Aucun taux » et « je n'ai pas su lire » ne doivent pas se ressembler."""
    taux, audit = fr.taux_du_coffre(tmp_path, coins=["BTC"], debut_ms=0, fin_ms=1)
    assert taux == {}
    assert audit["status"] == "COFFRE_ABSENT"
