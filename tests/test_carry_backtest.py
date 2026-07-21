"""Tests du BACKTEST CARRY (21/07) — rejouer nos vraies passes sous d'autres réglages.

Ce qu'ils PROUVENT :
  * on RE-DÉCIDE (le moteur du live est rappelé), on ne re-filtre pas un verdict figé ;
  * une donnée manquante rend None — on ne comble JAMAIS un trou pour faire tourner la simu ;
  * zéro donnée ⇒ zéro résultat (jamais un chiffre sorti de rien) ;
  * le mode BACKTEST ne touche jamais le PnL live ;
  * 🔴 un gain obtenu en BAISSANT la sécurité de liquidation est REFUSÉ — un backtest sur une
    fenêtre calme ne peut pas voir la queue qu'on vient de rendre possible.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.carry_backtest import (PASSES_MIN, Config, balayer, grille_defaut,
                                                    grouper_par_passe, redecider, rejouer,
                                                    verdict)

T0 = 1_760_000_000_000
PASSE = 600_000                      # 10 min, la cadence réelle du feeder

#: profils réalistes (funding, base bps, liquidité $, levier max venue, pire hausse)
PROFILS = {"BTC": (0.125, 12.0, 4.0e5, 10.0, 0.12), "ETH": (0.125, 6.0, 3.7e5, 10.0, 0.22),
           "SOL": (0.125, 10.0, 1.0e5, 5.0, 0.31), "PUMP": (0.300, 25.0, 3.0e4, 3.0, 0.82)}


def _lignes(n_passes=40, profils=None):
    profils = profils or PROFILS
    return [{"ts_ms": T0 + i * PASSE, "coin": c, "funding_bps_h": f, "base_bps": b,
             "liquidite_spot_usd": liq, "levier_max": lm, "pire_hausse_observee": pi,
             "perp_px": 100.0}
            for i in range(n_passes) for c, (f, b, liq, lm, pi) in profils.items()]


# ------------------------------------------------------------------ groupement (anti-lookahead)

def test_une_passe_est_un_INSTANT_et_les_passes_sont_ordonnees():
    g = grouper_par_passe(_lignes(3))
    assert [ts for ts, _ in g] == [T0, T0 + PASSE, T0 + 2 * PASSE]
    assert all(len(lot) == len(PROFILS) for _, lot in g)


def test_lignes_sans_ts_ou_sans_coin_sont_ignorees():
    assert grouper_par_passe([{"coin": "BTC"}, {"ts_ms": T0}, {}, None]) == []


# ------------------------------------------------------------------ re-décision

def test_on_RE_DECIDE_le_levier_change_avec_la_securite():
    """Le cœur de l'honnêteté du backtest : changer un paramètre change VRAIMENT la décision."""
    # 21/07 : funding remonte a 3,0 — le break-even inclut desormais la SORTIE, un funding de
    # 0,30 ne rembourse plus l'aller-retour sous le plafond par defaut. Le fixture doit tester
    # le LEVIER, pas buter sur la porte de break-even.
    ligne = {"coin": "X", "funding_bps_h": 3.0, "base_bps": 5.0, "liquidite_spot_usd": 4e5,
             "levier_max": 10.0, "pire_hausse_observee": 0.20, "perp_px": 100.0}
    lache = redecider(ligne, Config(securite_liquidation=1.0))
    serre = redecider(ligne, Config(securite_liquidation=3.0))
    assert lache is not None and serre is not None
    assert lache[1]["levier_utilise"] > serre[1]["levier_utilise"]


def test_le_plancher_de_break_even_est_un_VRAI_parametre():
    ligne = {"coin": "X", "funding_bps_h": 0.125, "base_bps": 5.0, "liquidite_spot_usd": 4e5,
             "levier_max": 10.0, "pire_hausse_observee": 0.10, "perp_px": 100.0}
    assert redecider(ligne, Config(max_break_even_h=1.0)) is None      # trop lent -> refusé
    assert redecider(ligne, Config(max_break_even_h=500.0)) is not None


@pytest.mark.parametrize("manquant", ["funding_bps_h", "base_bps", "liquidite_spot_usd",
                                      "levier_max", "pire_hausse_observee", "coin"])
def test_une_donnee_manquante_rend_None_jamais_une_valeur_comblee(manquant):
    ligne = {"coin": "X", "funding_bps_h": 0.30, "base_bps": 5.0, "liquidite_spot_usd": 4e5,
             "levier_max": 10.0, "pire_hausse_observee": 0.20}
    ligne.pop(manquant)
    assert redecider(ligne, Config()) is None


def test_un_levier_max_absurde_ecarte_le_coin_sans_lever():
    for lm in (0.0, -3.0, None, float("nan")):
        ligne = {"coin": "X", "funding_bps_h": 0.3, "base_bps": 5.0, "liquidite_spot_usd": 4e5,
                 "levier_max": lm, "pire_hausse_observee": 0.2}
        assert redecider(ligne, Config()) is None


def test_le_backtest_utilise_le_snapshot_si_le_funding_de_decision_manque():
    ligne = {"coin": "X", "funding_snapshot_bps_h": 3.0, "base_bps": 5.0,
             "liquidite_spot_usd": 4e5, "levier_max": 10.0, "pire_hausse_observee": 0.10}
    rd = redecider(ligne, Config())
    assert rd is not None and rd[0]["funding_bps_h"] == 3.0


# ------------------------------------------------------------------ rejeu

def test_zero_donnee_donne_zero_resultat_jamais_un_chiffre():
    r = rejouer([], Config())
    assert (r.passes, r.pnl_total_usd, r.insuffisant) == (0, 0.0, True)
    assert rejouer(_lignes(1), Config()).passes == 0        # une seule passe = aucun écoulement


def test_trop_peu_de_passes_est_DIT_insuffisant():
    assert rejouer(_lignes(PASSES_MIN - 1), Config()).insuffisant is True
    assert rejouer(_lignes(PASSES_MIN + 5), Config()).insuffisant is False


def test_le_rejeu_ouvre_accrue_et_ne_touche_jamais_le_mode_LIVE():
    r = rejouer(_lignes(40), Config())
    assert r.ouvertures > 0
    assert r.funding_accru_ouvert_usd > 0            # le temps a coulé, le funding s'est accru
    assert r.resume()["mode"] == "BACKTEST"
    assert r.resume()["real_execution"] is False


def test_le_pnl_exclut_le_latent_de_base_reversible():
    """`pnl_total` = réalisé + funding ENCAISSÉ. Le latent de base est réversible : le
    compter comme un gain, c'est maquiller (leçon du yoyo du 20/07)."""
    r = rejouer(_lignes(40), Config())
    assert r.pnl_total_usd == pytest.approx(r.realise_usd + r.funding_accru_ouvert_usd)


def test_les_memes_donnees_donnent_le_meme_resultat_deterministe():
    d = _lignes(30)
    assert rejouer(d, Config()).resume() == rejouer(d, Config()).resume()


def test_plus_de_slots_ne_peut_pas_ouvrir_moins_de_positions():
    d = _lignes(30)
    petit = rejouer(d, Config(max_slots=1)).positions_finales
    grand = rejouer(d, Config(max_slots=20)).positions_finales
    assert grand >= petit


# ------------------------------------------------------------------ balayage & verdict

def test_le_balayage_contient_TOUJOURS_la_config_de_production():
    """Sans point de comparaison, « le meilleur » ne veut rien dire."""
    assert Config() in [c for c in grille_defaut()]
    assert any(r.config == Config() for r in balayer(_lignes(20)))


def test_le_balayage_est_trie_par_pnl_decroissant():
    res = balayer(_lignes(25))
    assert [r.pnl_total_usd for r in res] == sorted((r.pnl_total_usd for r in res), reverse=True)


def test_verdict_sans_donnees_dit_AUCUNE_DONNEE_et_explique_quoi_faire():
    v = verdict([])
    assert v["conclusion"] == "AUCUNE DONNEE"
    assert "carry_scan.jsonl" in v["detail"]


def test_verdict_sur_trop_peu_de_passes_refuse_de_conclure():
    assert verdict(balayer(_lignes(3)))["conclusion"] == "DONNEES INSUFFISANTES"


def test_UN_GAIN_PAR_BAISSE_DE_SECURITE_EST_REFUSE():
    """🔴 LE garde-fou du module. Baisser `securite_liquidation` augmente mécaniquement le
    levier, donc le funding encaissé. Une fenêtre sans krach ne contient PAS la liquidation
    qu'on vient de rendre possible : le PnL monte, le risque de ruine aussi, et seul le
    premier est mesuré. L'outil ne doit jamais recommander ça."""
    v = verdict(balayer(_lignes(40)))
    if v["conclusion"].startswith("GAIN REFUSE"):
        assert "securite" in v["detail"]
        assert v["meilleur_a_securite_egale"] is not None
    else:
        # si le vainqueur n'a pas baissé la sécurité, il ne doit surtout pas l'avoir fait
        gagnante = next(r for r in balayer(_lignes(40)))
        assert gagnante.config.securite_liquidation >= Config().securite_liquidation


def test_le_verdict_avertit_toujours_sur_le_regime_de_marche():
    v = verdict(balayer(_lignes(40)))
    txt = v.get("avertissement") or v.get("detail") or ""
    assert txt                                       # jamais un verdict nu
