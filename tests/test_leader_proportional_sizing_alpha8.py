"""ALPHA-8 — taille de copie fidèle au leader, bornée par la capacité.

Les trois preuves qui comptent : un NAV de leader absent ne devient jamais une taille « raisonnable » ;
aucune taille ne dépend d'un résultat futur ; et une allocation n'est retenue que si le ROI net ET le
drawdown s'améliorent — pas parce que le PnL nominal a grossi avec l'exposition.

Paper uniquement : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copying import leader_proportional_sizing as LPS  # noqa: E402


def _taille(**kw):
    base = dict(capacite_l2_usd=10_000.0, budget_risque_usd=5_000.0, equity_suiveur_usd=1_000.0,
                delta_notional_leader_usd=100_000.0, nav_leader_usd=1_000_000.0)
    base.update(kw)
    return LPS.taille_cible(**base)


# ═══════════════ NAV absent : jamais remplacé par une taille de confort ═══════════════
def test_nav_leader_absent_rend_la_proportion_non_mesurable():
    f = LPS.fraction_leader(100_000.0, None)
    assert f["fraction"] is None and f["raison"] == "NAV_LEADER_NON_MESURABLE"
    f0 = LPS.fraction_leader(100_000.0, 0.0)
    assert f0["fraction"] is None


def test_sans_nav_aucune_position_nest_dimensionnee():
    r = _taille(nav_leader_usd=None)
    assert r["mesurable"] is False and r["taille_usd"] is None
    assert "NAV_LEADER_NON_MESURABLE" in r["manquantes"]


def test_toute_borne_manquante_annule_le_sizing():
    for absent in ("capacite_l2_usd", "budget_risque_usd", "equity_suiveur_usd"):
        r = _taille(**{absent: None})
        assert r["taille_usd"] is None and r["mesurable"] is False


# ═══════════════ proportion et plafond ═══════════════
def test_fraction_est_plafonnee_et_le_signale():
    f = LPS.fraction_leader(500_000.0, 1_000_000.0)      # 50 % brut
    assert f["fraction_brute"] == 0.5 and f["fraction"] == LPS.FRACTION_MAX and f["plafonnee"] is True
    petite = LPS.fraction_leader(10_000.0, 1_000_000.0)  # 1 %
    assert petite["fraction"] == 0.01 and petite["plafonnee"] is False


def test_le_signe_du_delta_ne_change_pas_la_taille():
    assert (LPS.fraction_leader(-100_000.0, 1_000_000.0)["fraction"]
            == LPS.fraction_leader(100_000.0, 1_000_000.0)["fraction"])


# ═══════════════ la borne qui mord est nommée ═══════════════
def test_la_proportion_leader_borne_la_taille():
    r = _taille()                                     # 1000 * 10 % = 100 $ < capacite/budget
    assert r["taille_usd"] == 100.0 and r["borne_active"] == "PROPORTION_LEADER"


def test_la_capacite_l2_borne_la_taille():
    r = _taille(capacite_l2_usd=25.0)
    assert r["taille_usd"] == 25.0 and r["borne_active"] == "CAPACITE_L2"


def test_le_budget_de_risque_borne_la_taille():
    r = _taille(budget_risque_usd=10.0)
    assert r["taille_usd"] == 10.0 and r["borne_active"] == "BUDGET_RISQUE"


# ═══════════════ aucun lookahead dans le sizing ═══════════════
def test_aucune_fonction_de_sizing_naccepte_un_resultat_futur():
    interdits = ("pnl", "forward", "futur", "future", "resultat", "outcome", "prix_sortie")
    for nom in ("fraction_leader", "taille_cible", "appliquer_caps", "copier_reduce"):
        params = inspect.signature(getattr(LPS, nom)).parameters
        for p in params:
            assert not any(mot in p.lower() for mot in interdits), \
                "%s(%s) : une taille ne doit jamais dependre d'un resultat futur" % (nom, p)


# ═══════════════ caps ═══════════════
def test_cap_coin_rabote_la_taille_et_est_nomme():
    r = LPS.appliquer_caps(100.0, coin="BTC", caps={"CAP_COIN": 120.0}, expositions={"BTC": 80.0})
    assert r["taille_usd"] == 40.0 and r["cap_actif"] == "CAP_COIN"


def test_le_cap_le_plus_contraignant_gagne():
    r = LPS.appliquer_caps(100.0, coin="BTC", direction="LONG", cluster="C1",
                           caps={"CAP_COIN": 90.0, "CAP_DIRECTION": 60.0, "CAP_CLUSTER": 30.0},
                           expositions={"BTC": 0.0, "LONG": 0.0, "C1": 0.0})
    assert r["taille_usd"] == 30.0 and r["cap_actif"] == "CAP_CLUSTER"


def test_cap_sature_donne_une_taille_nulle():
    r = LPS.appliquer_caps(100.0, coin="BTC", caps={"CAP_COIN": 50.0}, expositions={"BTC": 50.0})
    assert r["taille_usd"] == 0.0


def test_sans_cap_declare_la_taille_est_inchangee():
    assert LPS.appliquer_caps(100.0)["taille_usd"] == 100.0


# ═══════════════ REDUCE proportionnel à NOTRE position ═══════════════
def test_reduce_proportionnel_a_notre_position_pas_au_notionnel_initial():
    """Le leader réduit de 40 % ; notre position vaut déjà 60 $ (et non les 100 $ d'origine)."""
    r = LPS.copier_reduce(fraction_reduite_leader=0.4, position_suiveur_usd=60.0)
    assert r["reduction_usd"] == 24.0 and r["position_restante_usd"] == 36.0
    assert r["fermeture_totale"] is False


def test_fermeture_totale():
    r = LPS.copier_reduce(fraction_reduite_leader=1.0, position_suiveur_usd=60.0)
    assert r["position_restante_usd"] == 0.0 and r["fermeture_totale"] is True


def test_fraction_de_reduce_invalide_reste_non_mesurable():
    for mauvaise in (None, -0.1, 1.5, "beaucoup"):
        assert LPS.copier_reduce(fraction_reduite_leader=mauvaise,
                                 position_suiveur_usd=60.0)["mesurable"] is False


# ═══════════════ turnover et frais ═══════════════
def test_turnover_et_frais_comptes_sur_laller_retour():
    c = LPS.cout_turnover(100.0, frais_ar_bps=9.0)
    assert c["turnover_usd"] == 200.0 and c["frais_usd"] == 0.09


# ═══════════════ allocation : ROI ET drawdown ═══════════════
def test_allocation_rejetee_si_le_drawdown_se_degrade():
    v = LPS.verdict_allocation(avec={"n_episodes": 50, "roi_net": 0.20, "max_drawdown": -0.30},
                               sans={"n_episodes": 50, "roi_net": 0.10, "max_drawdown": -0.10})
    assert v["statut"] == "REJETE" and v["retenu"] is False
    assert v["roi_ameliore"] is True and v["drawdown_pas_degrade"] is False


def test_allocation_retenue_si_roi_monte_et_drawdown_ne_se_degrade_pas():
    v = LPS.verdict_allocation(avec={"n_episodes": 50, "roi_net": 0.20, "max_drawdown": -0.09},
                               sans={"n_episodes": 50, "roi_net": 0.10, "max_drawdown": -0.10})
    assert v["statut"] == "RETENU" and v["retenu"] is True and v["delta_roi"] > 0


def test_allocation_non_concluante_sans_echantillon():
    v = LPS.verdict_allocation(avec={"n_episodes": 5, "roi_net": 1.0, "max_drawdown": -0.01},
                               sans={"n_episodes": 5, "roi_net": 0.1, "max_drawdown": -0.5})
    assert v["statut"] == "NON_CONCLUANT" and v["retenu"] is False


def test_allocation_non_mesurable_si_le_drawdown_manque():
    v = LPS.verdict_allocation(avec={"n_episodes": 50, "roi_net": 0.2, "max_drawdown": None},
                               sans={"n_episodes": 50, "roi_net": 0.1, "max_drawdown": -0.1})
    assert v["statut"] == "NON_MESURABLE" and v["retenu"] is False


# ═══════════════ sécurité ═══════════════
def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "copying" / "leader_proportional_sizing.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans leader_proportional_sizing: %s" % interdit
