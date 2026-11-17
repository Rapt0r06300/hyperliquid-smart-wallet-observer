"""EXPLOITER UNE MINE PLUS GRANDE QUE LA MÉMOIRE — par galeries, sans trou et sans double compte.

D'OÙ VIENT CE MODULE (mesure du 16/11/2026). Le coffre LOCAL contient 5 427 shards et
**162 286 723 lignes**. Le pont du labo plafonne à 8 000 000 de lignes materialisées : il voit donc
au mieux **5 % du corpus**, et le dit honnêtement. Mais « tronqué et déclaré » n'est pas
« exploité ».

`plan_de_fouille` découpe l'axe du temps en GALERIES dont chacune tient dans le budget mémoire du
moment. Mesure sur le coffre réel : les 162 286 723 lignes tiennent en **35 galeries** avec un
budget de 4,7 M lignes, couverture complète, plan calculé en 2,3 s.

Ces tests verrouillent ce qui rend cette fouille honnête :

* une ligne appartient à **exactement une** galerie — un trou la perdrait, un recouvrement la
  compterait deux fois, et les deux falsifieraient toute mesure agrégée ;
* le budget suit la mémoire RÉELLEMENT libre, à la baisse comme à la hausse ;
* une galerie qu'on ne peut pas découper est **dite**, pas déguisée ;
* Ctrl+C ne perd aucune galerie terminée, et une reprise ne les refait pas ;
* l'agrégation REFUSE ce qui ne s'agrège pas (une moyenne de moyennes) au lieu de le moyenner.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import plan_de_fouille as PF  # noqa: E402

HEURE = 3_600_000
T0 = 1_790_000_000_000


def _shard(famille: str, nom: str, t0: int, t1: int, lignes: int, coins=("BTC",)) -> dict:
    return {"famille": famille, "shard": f"runtime/coffre_certifie/local/shards/{famille}/{nom}",
            "sha256": "0" * 64, "octets": lignes * 100, "deposes": lignes,
            "coins": list(coins), "ts_min_ms": t0, "ts_max_ms": t1}


# ───────────────── la couverture : tout le corpus, chaque ligne une seule fois ─────────────────
def test_les_galeries_couvrent_TOUT_sans_trou_ni_recouvrement():
    shards = [_shard("fills_forward", f"s{i}", T0 + i * 10 * HEURE,
                     T0 + (i + 1) * 10 * HEURE - 1, 300_000) for i in range(10)]
    plan = PF.galeries(shards, familles=["fills_forward"], budget=500_000)
    controle = PF.couverture(plan)
    assert controle["complete"] is True
    assert controle["trous"] == []
    assert controle["recouvrements"] == []
    gals = plan["galeries"]
    assert len(gals) > 1, "un budget inferieur au corpus doit produire plusieurs galeries"
    # contiguite EXACTE : la fin d'une galerie touche le debut de la suivante, a la milliseconde
    for avant, apres in zip(gals, gals[1:]):
        assert apres["debut_ms"] == avant["fin_ms"] + 1
    # les bords epousent la fenetre du corpus : rien avant la premiere, rien apres la derniere
    assert gals[0]["debut_ms"] == plan["fenetre_ms"][0]
    assert gals[-1]["fin_ms"] == plan["fenetre_ms"][1]


def test_aucune_ligne_ne_se_perd_entre_l_index_et_le_plan():
    """La somme des estimations doit égaler les lignes indexées (au ms d'arrondi près)."""
    shards = [_shard("bbo", f"b{i}", T0 + i * HEURE, T0 + (i + 1) * HEURE - 1, 111_111)
              for i in range(7)]
    plan = PF.galeries(shards, familles=["bbo"], budget=200_000)
    indexees = plan["lignes_indexees"]
    assert indexees == 7 * 111_111
    assert abs(plan["lignes_estimees"] - indexees) <= len(plan["galeries"])


def test_un_budget_IMPOSSIBLE_produit_une_galerie_dite_INDIVISIBLE():
    """Si une seule milliseconde porte plus que le budget, on l'émet seule et on le DIT."""
    shards = [_shard("micro_bbo", "dense", T0, T0 + 9, 1_000_000)]   # 100 000 lignes par ms
    plan = PF.galeries(shards, familles=["micro_bbo"], budget=1_000)
    assert plan["galeries"], "un budget trop petit ne doit pas rendre un plan vide"
    assert any(g["indivisible"] for g in plan["galeries"])
    controle = PF.couverture(plan)
    # une galerie indivisible depasse le budget SANS etre un echec : elle est declaree.
    assert controle["indivisibles"]
    assert controle["depassements"] == []
    assert controle["complete"] is True


def test_un_shard_SANS_BORNES_sort_a_part_et_jamais_en_silence():
    shards = [_shard("position", "date", T0, T0 + HEURE, 10_000),
              {**_shard("position", "muet", 0, 0, 5_000), "ts_min_ms": None, "ts_max_ms": None}]
    plan = PF.galeries(shards, familles=["position"], budget=100_000)
    assert len(plan["sans_bornes"]) == 1
    assert PF.couverture(plan)["sans_bornes"] == 1


def test_la_couverture_DENONCE_un_trou_et_un_recouvrement():
    """Le contrôle doit échouer sur un plan falsifié — sinon il ne contrôle rien."""
    trou = {"schema": PF.SCHEMA, "budget": 1_000, "fenetre_ms": [0, 99],
            "galeries": [{"rang": 1, "debut_ms": 0, "fin_ms": 40, "lignes_estimees": 10},
                         {"rang": 2, "debut_ms": 60, "fin_ms": 99, "lignes_estimees": 10}]}
    assert PF.couverture(trou)["trous"]
    assert PF.couverture(trou)["complete"] is False
    chevauche = {"schema": PF.SCHEMA, "budget": 1_000, "fenetre_ms": [0, 99],
                 "galeries": [{"rang": 1, "debut_ms": 0, "fin_ms": 70, "lignes_estimees": 10},
                              {"rang": 2, "debut_ms": 50, "fin_ms": 99, "lignes_estimees": 10}]}
    assert PF.couverture(chevauche)["recouvrements"]
    assert PF.couverture(chevauche)["complete"] is False


# ───────────────── le budget : il suit la mémoire réelle, il ne l'espère pas ─────────────────
def test_le_budget_SUIT_la_memoire_libre_a_la_baisse():
    large = PF.budget_lignes(dispo_octets=16 * 10**9, part=0.3)
    maigre = PF.budget_lignes(dispo_octets=10 * 10**6, part=0.3)
    assert large["lignes"] > maigre["lignes"]
    assert maigre["lignes"] >= PF.BUDGET_PLANCHER_LIGNES
    assert large["lignes"] <= PF.BUDGET_PLAFOND_LIGNES
    # le plancher et le plafond sont DITS, pour qu'on sache que la mesure a ete bornee
    assert maigre["borne_appliquee"] == "PLANCHER"
    assert large["borne_appliquee"] == "PLAFOND"


def test_une_memoire_minuscule_ne_rend_JAMAIS_un_budget_nul():
    """Un budget de zero ligne ferait une fouille infinie de galeries vides."""
    assert PF.budget_lignes(dispo_octets=0)["lignes"] >= PF.BUDGET_PLANCHER_LIGNES


# ───────────────── le parcours : rien ne se perd, rien ne se refait ─────────────────
def _plan_trois_galeries():
    shards = [_shard("fills_forward", f"s{i}", T0 + i * HEURE, T0 + (i + 1) * HEURE - 1, 100_000)
              for i in range(3)]
    return PF.galeries(shards, familles=["fills_forward"], budget=100_000)


def test_un_CTRL_C_garde_les_galeries_DEJA_FAITES(tmp_path):
    plan = _plan_trois_galeries()
    journal = tmp_path / "journal.jsonl"
    vues: list[int] = []

    def mesurer(galerie):
        vues.append(galerie["rang"])
        if len(vues) == 3:
            raise KeyboardInterrupt
        return {"lignes_lues": 1_000}

    resultat = PF.parcourir(plan, mesurer, journal=journal)
    assert resultat["etat"] == "INTERROMPU"
    assert resultat["galeries_faites"] == 2
    assert resultat["galeries_restantes"] >= 1
    # les deux galeries terminees sont SUR LE DISQUE, pas seulement en memoire
    lignes = [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 2
    assert resultat["lignes_lues"] == 2_000


def test_une_REPRISE_ne_refait_pas_une_galerie_deja_mesuree(tmp_path):
    plan = _plan_trois_galeries()
    journal = tmp_path / "journal.jsonl"
    appels: list[int] = []

    def mesurer(galerie):
        appels.append(galerie["rang"])
        if galerie["rang"] == 3 and len(appels) < 4:
            raise KeyboardInterrupt
        return {"lignes_lues": 7}

    premier = PF.parcourir(plan, mesurer, journal=journal)
    assert premier["etat"] == "INTERROMPU" and premier["galeries_faites"] == 2
    second = PF.parcourir(plan, mesurer, journal=journal)
    assert second["etat"] == "COMPLET"
    assert second["galeries_reprises"] == 2, "les galeries du journal doivent etre reprises"
    assert second["galeries_faites"] == 1, "seule la galerie interrompue doit etre refaite"
    assert second["lignes_lues"] == 21
    assert appels.count(1) == 1, "la galerie 1 ne doit etre mesuree qu'UNE fois"


def test_une_ligne_de_journal_TRONQUEE_est_refaite_jamais_crue(tmp_path):
    """Une coupure peut laisser une ligne JSON incomplète : on la refait, on ne l'interprète pas."""
    plan = _plan_trois_galeries()
    journal = tmp_path / "journal.jsonl"
    journal.write_text('{"empreinte": "abc", "mesur', encoding="utf-8")
    resultat = PF.parcourir(plan, lambda g: {"lignes_lues": 5}, journal=journal)
    assert resultat["etat"] == "COMPLET"
    assert resultat["galeries_reprises"] == 0
    assert resultat["galeries_faites"] == len(plan["galeries"])


def test_le_parcours_compare_l_estimation_a_la_REALITE(tmp_path):
    plan = _plan_trois_galeries()
    resultat = PF.parcourir(plan, lambda g: {"lignes_lues": g["lignes_estimees"] // 2},
                            journal=tmp_path / "j.jsonl")
    assert resultat["ecart_estimation"] == pytest.approx(-0.5, abs=0.01)


# ───────────────── l'agrégation : honnête ou refusée, jamais approximative ─────────────────
def test_l_agregation_SOMME_les_entiers_et_FUSIONNE_les_histogrammes():
    total = PF.agreger([
        {"lignes_lues": 10, "lignes_par_jour": {"2026-11-13": 4, "2026-11-14": 6},
         "coins": ["BTC", "ETH"], "instant_min": 500, "instant_max": 900},
        {"lignes_lues": 5, "lignes_par_jour": {"2026-11-14": 5},
         "coins": ["ETH", "SOL"], "instant_min": 100, "instant_max": 700},
    ])
    assert total["sommes"]["lignes_lues"] == 15
    assert total["histogrammes"]["lignes_par_jour"] == {"2026-11-13": 4, "2026-11-14": 11}
    assert total["unions"]["coins"] == ["BTC", "ETH", "SOL"]
    assert total["extremums"]["instant_min"] == 100
    assert total["extremums"]["instant_max"] == 900


def test_l_agregation_REFUSE_une_moyenne_au_lieu_de_moyenner_des_moyennes():
    """Faire la moyenne de moyennes de tailles différentes est un faux ; un faux muet est pire."""
    total = PF.agreger([{"pnl_bps": 1.5}, {"pnl_bps": -3.0}])
    assert "pnl_bps" not in total["sommes"]
    assert total["non_agregeable"]["pnl_bps"] == "float"
