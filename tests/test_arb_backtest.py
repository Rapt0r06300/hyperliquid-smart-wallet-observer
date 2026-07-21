"""Tests du BACKTEST ARBITRAGE (21/07) — « il n'ouvre que deux fois par mois ».

Flo avait raison de trouver ça anormal, et la mauvaise réponse aurait été de baisser le seuil :
plus de trades ≠ plus d'edge. Ces tests verrouillent le bon ordre de raisonnement.

Ce qu'ils PROUVENT :
  * la CONVERGENCE est mesurée avant tout balayage de seuils, sans coût ni seuil dedans ;
  * une série qui ne converge pas produit « PAS D'EDGE », jamais un seuil « optimisé » ;
  * aucun lookahead : la sortie est cherchée strictement APRÈS l'entrée ;
  * les coûts d'aller-retour sont TOUJOURS payés ;
  * un trade encore ouvert à la fin de la série n'est pas compté (ce serait l'inventer) ;
  * données insuffisantes ⇒ pas de chiffre.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting.arb_backtest import (ENTREES_MIN, OBSERVATIONS_MIN, ConfigArb,
                                                  balayer, charger_serie, convergence,
                                                  grille_defaut, rejouer, verdict)

T0 = 1_784_000_000.0
PAS = 300.0                     # 5 min entre deux observations


def _serie_convergente(n=400, amplitude=30.0):
    """Un écart qui part fort et se referme, puis repart. Le cycle fait 5 points alors que
    l'horizon testé en fait 6 : sans ce décalage, la série serait PÉRIODIQUE et la variation
    à l'horizon vaudrait exactement 0 — un fixture dégénéré qui ne prouverait rien."""
    pts, t = [], T0
    while len(pts) < n:
        for e in (amplitude, amplitude * 0.5, amplitude * 0.2, 0.5, 0.2):
            pts.append((t, e))
            t += PAS
    return {"X": pts[:n]}


def _serie_divergente(n=400):
    """Un écart qui ne se referme jamais (marche au hasard bornée, sans retour)."""
    pts, t = [], T0
    for i in range(n):
        pts.append((t, 20.0 + (i % 7) - 3.0))
        t += PAS
    return {"X": pts}


# ------------------------------------------------------------------ chargement

def test_charger_serie_ignore_les_lignes_sans_ecart(tmp_path):
    """Le champ `ecart_prix_bps` est récent : les vieilles lignes n'en ont pas. On ne les
    complète JAMAIS — un zéro inventé fausserait toute l'étude de convergence."""
    p = tmp_path / "v.jsonl"
    p.write_text("\n".join([
        json.dumps({"ts": T0, "coin": "BTC", "ecart_prix_bps": 12.0}),
        json.dumps({"ts": T0 + 60, "coin": "BTC"}),                       # pas d'écart
        json.dumps({"ts": T0 + 120, "coin": "BTC", "ecart_prix_bps": None}),
        json.dumps({"coin": "BTC", "ecart_prix_bps": 5.0}),               # pas de ts
        "{ pas du json",
    ]), encoding="utf-8")
    s = charger_serie(chemin=p)
    assert s == {"BTC": [(T0, 12.0)]}


def test_charger_serie_fichier_absent_rend_un_dict_vide(tmp_path):
    assert charger_serie(tmp_path) == {}


def test_la_serie_est_triee_dans_le_temps(tmp_path):
    p = tmp_path / "v.jsonl"
    p.write_text("\n".join(json.dumps({"ts": T0 + d, "coin": "X", "ecart_prix_bps": d})
                           for d in (300, 100, 200)), encoding="utf-8")
    assert [t for t, _ in charger_serie(chemin=p)["X"]] == [T0 + 100, T0 + 200, T0 + 300]


# ------------------------------------------------------------------ convergence (la 1re question)

def test_trop_peu_d_observations_ne_conclut_RIEN():
    c = convergence({"X": [(T0 + i * PAS, 20.0) for i in range(OBSERVATIONS_MIN - 1)]})
    assert c["insuffisant"] is True
    assert "verdict" not in c


def test_une_serie_qui_converge_est_reconnue():
    c = convergence(_serie_convergente(), seuil_bps=10.0, horizons_h=(0.5, 1.0))
    assert c["insuffisant"] is False
    assert c["horizons"]["0.5h"]["delta_moyen_bps"] < 0
    assert "CONVERGE" in c["verdict"].upper()


def test_une_serie_qui_ne_converge_pas_TUE_la_strategie_sans_toucher_au_seuil():
    """Le résultat le plus important du module : quand ça ne converge pas, on ne propose
    PAS un seuil plus bas — on dit qu'il n'y a pas d'edge."""
    c = convergence(_serie_divergente(), seuil_bps=10.0, horizons_h=(0.5, 1.0))
    assert "AUCUNE CONVERGENCE" in c["verdict"]
    v = verdict(c, balayer(_serie_divergente()))
    assert v["conclusion"] == "PAS D'EDGE D'ARBITRAGE SUR CES DONNEES"
    assert "baisser le seuil" in v["avertissement"].lower()


def test_la_convergence_ne_regarde_QUE_le_futur():
    """Une observation ne peut être appariée qu'avec une observation postérieure."""
    pts = [(T0, 30.0)] + [(T0 - i * PAS, 0.1) for i in range(1, 300)]
    c = convergence({"X": sorted(pts)}, seuil_bps=10.0, horizons_h=(1.0,))
    assert c["horizons"]["1.0h"]["n"] == 0        # rien après T0 -> aucune paire


# ------------------------------------------------------------------ rejeu (la 2e question)

def test_les_couts_sont_TOUJOURS_payes():
    """Une capture égale au coût donne un PnL nul, pas un gain."""
    serie = {"X": [(T0, 8.0), (T0 + PAS, 0.0)]}
    r = rejouer(serie, ConfigArb(seuil_ouverture_bps=8.0, seuil_sortie_bps=1.0, cout_ar_bps=8.0))
    assert r.entrees == 1
    assert r.pnl_usd == pytest.approx(0.0, abs=1e-9)
    assert r.gagnants == 0                        # « pas perdant » n'est pas « gagnant »


def test_un_ecart_qui_s_ELARGIT_coute_de_l_argent():
    """Entrée à +20, l'écart s'élargit à +35 et on sort par âge : capture −15 bps, coûts
    payés en plus. C'est le vrai cas défavorable (un passage par zéro, lui, est GAGNANT :
    on est short le spread des deux côtés)."""
    serie = {"X": [(T0, 20.0)] + [(T0 + i * 3600.0, 35.0) for i in range(1, 7)]}
    r = rejouer(serie, ConfigArb(seuil_ouverture_bps=15.0, seuil_sortie_bps=1.0, age_max_h=4.0))
    assert r.entrees == 1 and r.gagnants == 0 and r.pnl_usd < 0


def test_un_passage_par_zero_est_un_GAIN_pas_une_perte():
    """+20 -> -0,5 : la sortie se déclenche de l'AUTRE côté de zéro. Short du spread des
    deux côtés du passage : capture 20 + 0,5 = 20,5 bps, pas 19,5."""
    serie = {"X": [(T0, 20.0), (T0 + PAS, -0.5)]}
    r = rejouer(serie, ConfigArb(seuil_ouverture_bps=15.0, seuil_sortie_bps=1.0, cout_ar_bps=8.0))
    assert r.entrees == 1 and r.capture_moyenne_bps == pytest.approx(20.5)
    assert r.pnl_usd == pytest.approx((20.5 - 8.0) / 1e4 * r.config.notional_usd)


def test_un_trade_NON_CLOS_a_la_fin_de_la_serie_n_est_pas_compte():
    """Le compter serait inventer une sortie qu'on n'a jamais observée."""
    serie = {"X": [(T0, 30.0), (T0 + PAS, 28.0), (T0 + 2 * PAS, 27.0)]}
    r = rejouer(serie, ConfigArb(seuil_ouverture_bps=15.0, seuil_sortie_bps=1.0, age_max_h=99.0))
    assert r.entrees == 0


def test_la_sortie_par_AGE_est_comptee_comme_telle():
    serie = {"X": [(T0, 30.0)] + [(T0 + i * 3600.0, 29.0) for i in range(1, 8)]}
    r = rejouer(serie, ConfigArb(seuil_ouverture_bps=15.0, seuil_sortie_bps=1.0, age_max_h=4.0))
    assert r.entrees == 1 and r.sorties_par_age == 1


def test_pas_de_chevauchement_on_repart_APRES_la_sortie():
    s = _serie_convergente(n=60, amplitude=30.0)
    r = rejouer(s, ConfigArb(seuil_ouverture_bps=15.0, seuil_sortie_bps=1.0))
    assert r.entrees <= len(s["X"]) // 2          # jamais une entrée à chaque point


def test_un_seuil_plus_haut_ne_peut_pas_produire_PLUS_d_entrees():
    s = _serie_convergente()
    bas = rejouer(s, ConfigArb(seuil_ouverture_bps=5.0)).entrees
    haut = rejouer(s, ConfigArb(seuil_ouverture_bps=25.0)).entrees
    assert haut <= bas


def test_trop_peu_d_entrees_est_DIT_insuffisant():
    serie = {"X": [(T0, 30.0), (T0 + PAS, 0.0)]}
    assert rejouer(serie, ConfigArb(seuil_ouverture_bps=15.0)).insuffisant is True


# ------------------------------------------------------------------ balayage & verdict

def test_le_balayage_contient_TOUJOURS_le_seuil_de_production():
    assert ConfigArb() in grille_defaut()


def test_le_balayage_est_trie_par_pnl_decroissant():
    res = balayer(_serie_convergente())
    assert [r.pnl_usd for r in res] == sorted((r.pnl_usd for r in res), reverse=True)


def test_le_verdict_ne_couronne_qu_un_reglage_avec_assez_d_entrees():
    res = balayer(_serie_convergente())
    v = verdict(convergence(_serie_convergente(), seuil_bps=10.0), res)
    if v.get("meilleur"):
        assert v["meilleur"]["entrees"] >= ENTREES_MIN


def test_le_verdict_rappelle_TOUJOURS_que_la_jambe_binance_est_conceptuelle():
    v = verdict(convergence(_serie_convergente(), seuil_bps=10.0), balayer(_serie_convergente()))
    txt = (v.get("avertissement") or "") + (v.get("detail") or "")
    assert txt                                     # jamais un verdict nu
