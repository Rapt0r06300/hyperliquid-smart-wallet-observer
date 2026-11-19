"""La porte funding : INCHANGÉE par défaut, MESURABLE quand les règlements observés sont fournis.

Le reçu gelé ne savait prouver le funding que d'une façon — « zéro, car aucun règlement franchi ».
Comme le funding se règle toutes les heures et que les horizons vont jusqu'à 1 h, un seul trade
franchissant une frontière rendait le segment INÉLIGIBLE : porte pratiquement infranchissable
(100 % des essais refusés). La mesure est déléguée à ``copy_vault_funding_realise``, qui existait
déjà et n'était branché nulle part. Ces tests verrouillent les deux versants.
"""
from __future__ import annotations

from decimal import Decimal

import hl_observer.backtesting.copy_vault_v21_frozen as V21

H = 3_600_000


def _trade(entree, sortie, *, coin="BTC", direction=1, notionnel=100.0):
    return {"coin": coin, "entry_ts_ms": entree, "exit_ts_ms": sortie,
            "notional_usd": notionnel, "direction": direction}


def _taux(par_heure, coin="BTC", *, bornes=(0, 12)):
    """{numero_heure: taux} -> structure attendue par funding_des_trades.

    On encadre volontairement par des règlements aux heures `bornes` : sans `couverture_ms`,
    le module déduit la fenêtre LUE du premier et du dernier règlement connus, et refuse tout
    épisode qui en sort (« je n'ai pas lu » n'est pas « rien à payer »). Un test ci-dessous
    verrouille ce garde-fou pour lui-même.
    """
    serie = {bornes[0]: "0", bornes[1]: "0"}
    serie.update({h: str(t) for h, t in par_heure.items()})
    return {coin: [(h * H, Decimal(v)) for h, v in sorted(serie.items())]}


def test_defaut_inchange_un_franchissement_reste_inmesurable():
    """Sans taux (cas v21 incumbent) : comportement historique, à la lettre."""
    recu = V21._funding_receipt([_trade(H + 10, 2 * H + 10)])
    assert recu["status"] == "UNMEASURABLE"
    assert recu["reason"] == "ACCEPTED_TRADE_CROSSES_FUNDING_BOUNDARY"
    assert recu["carry_pnl_usd"] is None


def test_defaut_inchange_zero_prouve_sans_franchissement():
    recu = V21._funding_receipt([_trade(H + 10, H + 20)])
    assert recu["status"] == "MEASURED_ZERO_NO_SETTLEMENT_CROSSED"
    assert recu["carry_pnl_usd"] == 0.0


def test_avec_reglements_observes_le_franchissement_devient_mesure():
    """Le cas qui bloquait tout : un trade franchit une frontière -> désormais MESURÉ."""
    recu = V21._funding_receipt([_trade(H + 10, 2 * H + 10)], _taux({2: "0.001"}))
    assert recu["status"] == "MEASURED"                       # statut CANONIQUE du dépôt
    assert recu["carry_pnl_usd"] is not None
    assert recu["settlement_crossing_count"] >= 1
    assert recu["provenance"]                                  # la provenance est dite, pas supposée
    assert "carry_pnl_usd_exact_decimal" in recu               # comptabilité exacte conservée


def test_fail_closed_hors_fenetre_lue_ne_devient_jamais_zero():
    """Un épisode hors de la fenêtre LUE reste INMESURABLE, surtout pas un funding inventé à 0.

    En réel la série de règlements est DENSE (mesuré : 576/576 frontières horaires couvertes),
    donc la panne qui compte n'est pas un trou interne : c'est un épisode qu'on n'a pas lu.
    """
    recu = V21._funding_receipt([_trade(20 * H + 10, 21 * H + 10)], _taux({2: "0.001"}))
    assert recu["status"] == "UNMEASURABLE"
    assert recu["carry_pnl_usd"] is None
    assert recu.get("reasons")                                 # on dit COMBIEN et POURQUOI


def test_sans_franchissement_les_taux_ne_changent_rien():
    """Fournir des taux ne doit pas transformer un zéro prouvé en autre chose."""
    sans = V21._funding_receipt([_trade(H + 10, H + 20)])
    avec = V21._funding_receipt([_trade(H + 10, H + 20)], _taux({2: "0.001"}))
    assert avec["status"] == sans["status"] == "MEASURED_ZERO_NO_SETTLEMENT_CROSSED"
    assert avec["carry_pnl_usd"] == 0.0


def test_un_seul_episode_inconnu_emporte_le_verdict():
    taux = _taux({2: "0.001"})
    bon = _trade(H + 10, 2 * H + 10)
    inconnu = _trade(20 * H + 10, 21 * H + 10)        # hors fenetre lue
    assert V21._funding_receipt([bon], taux)["status"] == "MEASURED"
    assert V21._funding_receipt([bon, inconnu], taux)["status"] == "UNMEASURABLE"


def test_la_porte_accepte_exactement_les_deux_statuts_mesures():
    """Le segment n'accepte que des MESURES, et les mêmes que `_reference_objective_status`."""
    acceptes = {"MEASURED_ZERO_NO_SETTLEMENT_CROSSED", "MEASURED"}
    produits = {
        V21._funding_receipt([_trade(H + 10, H + 20)])["status"],
        V21._funding_receipt([_trade(H + 10, 2 * H + 10)])["status"],
        V21._funding_receipt([_trade(H + 10, 2 * H + 10)], _taux({2: "0.001"}))["status"],
        V21._funding_receipt([_trade(9 * H + 10, 10 * H + 10)], _taux({2: "0.001"}))["status"],
    }
    assert produits == acceptes | {"UNMEASURABLE"}


def test_trade_malforme_reste_inmesurable_avec_ou_sans_taux():
    casse = [{"coin": "BTC", "entry_ts_ms": "x", "exit_ts_ms": 2 * H}]
    assert V21._funding_receipt(casse)["status"] == "UNMEASURABLE"
    assert V21._funding_receipt(casse, _taux({2: "0.001"}))["status"] == "UNMEASURABLE"


def test_le_garde_de_couverture_distingue_non_lu_et_rien_a_payer():
    """Hors de la fenêtre LUE : inconnu. Dans la fenêtre, entre deux règlements : zéro MESURÉ."""
    # un seul règlement connu -> fenêtre lue réduite à cet instant : l'épisode en sort
    etroit = {"BTC": [(2 * H, Decimal("0.001"))]}
    hors = V21._funding_receipt([_trade(H + 10, 2 * H + 10)], etroit)
    assert hors["status"] == "UNMEASURABLE"
    assert "FUNDING_RATES_DO_NOT_COVER_EPISODE" in (hors.get("reasons") or {})
    # dans la fenêtre lue mais sans règlement traversé -> 0 MESURÉ, pas une ignorance
    dedans = V21._funding_receipt([_trade(3 * H + 10, 3 * H + 20)], _taux({2: "0.001"}))
    assert dedans["status"] == "MEASURED_ZERO_NO_SETTLEMENT_CROSSED"   # mesure, pas ignorance
    assert dedans["carry_pnl_usd"] == 0.0
