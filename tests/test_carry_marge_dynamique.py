"""MARGE DYNAMIQUE — pourquoi le PnL « ne bougeait jamais », et pourquoi ça n'ajoute pas de risque.

CONSTAT (19/07) : marge 50 $ × levier 1,5 = 75 $ de notional, sur 1 000 $ d'equity.
À 0,125 bps/h, ça rapporte **2,25 centimes par jour** — invisible sur un dashboard à 2 décimales.
92 % du capital dormait.

⚠️ CE QUE CES TESTS PROTÈGENT SURTOUT : que l'on grossisse la MARGE et **jamais le LEVIER**.
Le levier 1,5 sur HYPE vient de la pire hausse MESURÉE (~29 %) : à levier 3, la jambe perp short
serait liquidée sur ce même mouvement. La distance à la liquidation dépend du levier, pas de la
taille — donc doubler la marge à levier constant double le revenu à risque de liquidation
INCHANGÉ. C'est le seul levier de revenu gratuit en risque.
"""
from __future__ import annotations

from hl_observer.funding.carry_marge_dynamique import (
    MARGE_MAX_USD, MARGE_MIN_USD, marge_par_position, revenu_journalier_usd)


def test_le_capital_inconnu_retombe_sur_la_marge_par_defaut():
    """RÈGLE DURE : on n'invente JAMAIS un capital. Inventer un capital = inventer un PnL."""
    for capital in (None, 0, -5, float("nan"), "1000", True):
        assert marge_par_position(capital_usd=capital, n_positions_visees=1,
                                  marge_defaut_usd=50.0) == 50.0


def test_la_reserve_de_marge_est_respectee():
    """1 000 $ avec 20 % de réserve -> 800 $ déployables, jamais 1 000."""
    m = marge_par_position(capital_usd=1000.0, n_positions_visees=1, part_max_par_coin=1.0)
    assert m == 800.0


def test_la_concentration_par_coin_est_plafonnee():
    """Une seule position ne prend pas tout le capital déployable, même si elle est seule."""
    m = marge_par_position(capital_usd=1000.0, n_positions_visees=1, part_max_par_coin=0.40)
    assert m == 320.0                                   # 800 × 0,40


def test_le_capital_se_repartit_entre_les_positions_visees():
    m = marge_par_position(capital_usd=1000.0, n_positions_visees=4, part_max_par_coin=1.0)
    assert m == 200.0                                   # 800 / 4


def test_un_plancher_evite_les_positions_insignifiantes():
    """Mieux vaut MOINS de positions correctement dimensionnées que N positions ridicules."""
    m = marge_par_position(capital_usd=100.0, n_positions_visees=50)
    assert m >= min(MARGE_MIN_USD, 80.0)


def test_un_plafond_dur_borne_le_dimensionnement():
    m = marge_par_position(capital_usd=10_000_000.0, n_positions_visees=1, part_max_par_coin=1.0)
    assert m == MARGE_MAX_USD


def test_le_revenu_journalier_est_le_chiffre_qui_manquait():
    """75 $ à 0,125 bps/h = 2,25 centimes/jour. Affiché, ce nombre évitait une journée de doute."""
    assert round(revenu_journalier_usd(notional_usd=75.0, funding_bps_h=0.125), 4) == 0.0225


def test_grossir_la_marge_multiplie_le_revenu_SANS_toucher_au_levier():
    """LE POINT CENTRAL : à levier constant, ×10 de marge = ×10 de revenu, et la distance à la
    liquidation ne bouge pas d'un centime (elle ne dépend que du levier)."""
    levier = 1.5
    petit = revenu_journalier_usd(notional_usd=50.0 * levier, funding_bps_h=0.125)
    gros = revenu_journalier_usd(notional_usd=500.0 * levier, funding_bps_h=0.125)
    assert round(gros / petit, 6) == 10.0


def test_la_marge_dynamique_est_VRAIMENT_utilisee_a_l_ouverture(tmp_path):
    """Preuve de câblage : sans capital -> notional 75 $ ; avec capital -> notional plus gros.
    Un module de sizing que personne n'appelle ne fait pas bouger un PnL."""
    from hl_observer.funding.carry_positions_store import charger_gestionnaire, tick_multi_sur_disque

    decision = {"coin": "HYPE", "viable": True, "funding_bps_h": 0.125, "base_bps": -1.5,
                "levier": 1.5, "cout_entree_bps": 12.47, "gain_net_24h_bps": 46.5,
                "liquidite_spot_usd": 150_000.0, "marge_ratio": 0.667, "levier_max": 10.0}
    inputs = {"coin": "HYPE", "perp_px": 61.0, "levier_utilise": 1.5, "marge_ratio": 0.667}
    mesures = {"HYPE": {"decision": decision, "inputs": inputs, "funding": 0.125,
                        "prix": 61.0, "base": -1.5}}

    tick_multi_sur_disque(tmp_path / "a", mesures, now_ms=1_800_000_000_000, max_slots=12)
    petit = charger_gestionnaire(tmp_path / "a").ouvertes["HYPE"]["notional_usdt"]

    tick_multi_sur_disque(tmp_path / "b", mesures, now_ms=1_800_000_000_000, max_slots=12,
                          capital_usd=1000.0)
    gros = charger_gestionnaire(tmp_path / "b").ouvertes["HYPE"]["notional_usdt"]

    assert petit == 75.0, "sans capital connu, on garde le comportement par defaut"
    assert gros > petit * 4, "avec 1 000 $ de capital, la position doit devenir VISIBLE (%s)" % gros


def test_le_levier_NE_CHANGE_PAS_avec_la_marge(tmp_path):
    """Le garde-fou le plus important de ce fichier : grossir ne doit pas rapprocher la liquidation."""
    from hl_observer.funding.carry_positions_store import charger_gestionnaire, tick_multi_sur_disque
    decision = {"coin": "HYPE", "viable": True, "funding_bps_h": 0.125, "base_bps": -1.5,
                "levier": 1.5, "cout_entree_bps": 12.47, "liquidite_spot_usd": 150_000.0,
                "marge_ratio": 0.667, "levier_max": 10.0}
    inputs = {"coin": "HYPE", "perp_px": 61.0, "levier_utilise": 1.5, "marge_ratio": 0.667}
    mesures = {"HYPE": {"decision": decision, "inputs": inputs, "funding": 0.125, "prix": 61.0}}
    tick_multi_sur_disque(tmp_path, mesures, now_ms=1_800_000_000_000, max_slots=12,
                          capital_usd=5000.0)
    pos = charger_gestionnaire(tmp_path).ouvertes["HYPE"]
    assert float(pos["levier"]) == 1.5, "le LEVIER doit rester celui que le risque a validé"


# ---------------- 20/07 : « notre pnl est ridicule » — le capital etait ENCORE fantome ----------------
# 19/07 : marge dynamique branchee sur une FONCTION inexistante -> 50 $. 20/07 : rebranchee sur
# des CLES inexistantes du bon fichier -> encore 50 $, 40 % du capital deploye. Ces tests lisent
# le VRAI schema de ui_simulation_state.json (history[-1].current_equity_usdt, starting).

import json as _json
from pathlib import Path as _Path

from hl_observer.funding.carry_paper_runtime import _capital_disponible


def _ecrire_etat(tmp_path, contenu):
    p = tmp_path / "runtime" / "data" / "ui_simulation_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(contenu), encoding="utf-8")


def test_capital_lu_dans_l_historique_d_equity_LE_VRAI_SCHEMA(tmp_path):
    _ecrire_etat(tmp_path, {"simulation_starting_equity_usdt": 1000.0,
                            "simulation_equity_history": [
                                {"current_equity_usdt": 1000.0},
                                {"current_equity_usdt": 998.4}]})
    assert _capital_disponible(tmp_path) == 998.4     # l'equity VIVANTE, pas le depart


def test_capital_replie_sur_l_equity_de_depart_si_l_historique_manque(tmp_path):
    _ecrire_etat(tmp_path, {"simulation_starting_equity_usdt": 1000.0})
    assert _capital_disponible(tmp_path) == 1000.0


def test_capital_absent_reste_None_jamais_invente(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT", raising=False)
    assert _capital_disponible(tmp_path) is None


def test_le_lanceur_declare_le_capital_en_repli():
    src = open("LANCER_HYPERSMART.cmd", encoding="utf-8", errors="replace").read()
    assert 'HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT=1000' in src
