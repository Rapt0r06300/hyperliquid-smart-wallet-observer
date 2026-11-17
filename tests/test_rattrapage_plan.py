"""L'ORDRE DU RATTRAPAGE : par rendement, pas par manque — et jamais deux taches a la fois.

CE QUE CES TESTS VERROUILLENT, ET D'OU CA VIENT. Le 15/11, le rattrapage du funding (94 h estimees)
est parti EN PARALLELE de celui des bougies journalieres (1,8 h). Les deux ont ete tues par le
systeme pour manque de memoire apres avoir servi 2 coins sur 261. Trois lecons, trois tests :

* on classe par **jours-coins par seconde**, donc le journalier passe devant le funding ;
* un funding sans prix en face ne mesure RIEN : la precedence passe avant le rendement ;
* la concurrence vaut 1, toujours.

Pur : aucune horloge, aucun fichier, aucun reseau.
"""
from __future__ import annotations

import pytest

from hl_observer.ops import rattrapage_plan as RP

JOUR = RP.JOUR_MS
NOW = 1_790_000_000_000


# ─────────────── le cout d'une tache, mesure sur la vraie pagination ───────────────
def test_une_page_de_funding_coute_bien_28_secondes_au_debit_historique():
    """Verification de l'estimation contre la MESURE du 15/11 : 28 s par page observees."""
    funding = RP.TACHES_PAR_NOM["funding-profond"]
    une_page = funding.jours_par_requete
    assert une_page == pytest.approx(20.83, abs=0.01), "500 points horaires = 20,83 jours"
    cout = funding.cout_s(1, budget_par_minute=100.0)
    assert cout == pytest.approx(27.0, abs=1.5), f"estime {cout:.1f} s, mesure ~28 s"


def test_le_journalier_prend_toute_l_histoire_d_un_coin_en_une_requete():
    jour = RP.TACHES_PAR_NOM["bougies-1d"]
    assert jour.jours_par_requete >= 1100.0, (
        "5 000 bougies journalieres = 5 000 jours d'un coup : c'est ce qui rend ce pas 50 fois "
        "moins cher que le funding pour la meme profondeur")
    assert jour.cout_s(1, budget_par_minute=100.0) < 70.0


def test_un_debit_nul_est_refuse_et_non_traite_comme_instantane():
    with pytest.raises(ValueError):
        RP.TACHES_PAR_NOM["bougies-1d"].cout_s(3, budget_par_minute=0.0)


def test_aucune_requete_quand_il_ne_manque_rien():
    for tache in RP.TACHES:
        assert tache.requetes_pour(0.0) == 0 and tache.requetes_pour(-5.0) == 0
        assert tache.requetes_pour(0.5) == 1, "il manque un demi-jour : une requete quand meme"


# ─────────────── le manque : les DEUX fronts du funding comptent ───────────────
def test_le_manque_de_funding_compte_le_creusage_ET_le_retard():
    """Ne compter que le retard est l'erreur qui a fait croire 115 coins « a jour » a 211 jours."""
    manque = RP.manque_funding(coins=["BTC"], etat_ancien={"BTC": NOW - 211 * JOUR},
                               etat_recent={"BTC": NOW - 2 * JOUR},
                               profondeur_j=1100.0, now_ms=NOW)["jours_coins"]
    assert manque == pytest.approx(1100 - 211 + 2, abs=0.1), (
        "889 jours a creuser PLUS 2 jours de retard : un coin a jour peut etre tres peu profond")


def test_un_coin_jamais_vu_manque_de_toute_la_profondeur():
    assert RP.manque_funding(coins=["NEUF"], etat_ancien={}, etat_recent={},
                             profondeur_j=1100.0, now_ms=NOW)["jours_coins"] == pytest.approx(1100.0)
    neuf = RP.manque_bougies(coins=["NEUF"], etat_serie={}, profondeur_j=208.0, now_ms=NOW,
                             pas_ms=RP.HEURE_MS)
    assert neuf["jours_coins"] == pytest.approx(208.0) and neuf["requetes"] == 1


def test_une_bougie_deja_tiree_ne_manque_que_de_son_retard():
    """Un premier tirage rend 5 000 bougies : la profondeur est acquise d'un coup, pas page a page."""
    manque = RP.manque_bougies(coins=["BTC"], etat_serie={"BTC": NOW - 3 * JOUR},
                               profondeur_j=208.0, now_ms=NOW, pas_ms=RP.JOUR_MS)
    assert manque["jours_coins"] == pytest.approx(3.0, abs=0.01)
    assert manque["requetes"] == 1, "3 jours de retard = UNE requete, pas 3/208e de requete"


def test_un_etat_illisible_est_traite_comme_absent_jamais_comme_complet():
    for pourri in ({"BTC": "hier"}, {"BTC": None}, {"BTC": {}}):
        assert RP.manque_bougies(coins=["BTC"], etat_serie=pourri, profondeur_j=208.0,
                                 now_ms=NOW, pas_ms=RP.JOUR_MS)["jours_coins"] == pytest.approx(208.0), (
            "un etat illisible doit faire RETIRER la donnee, jamais la declarer complete")


# ─────────────── l'ordre : rendement, puis precedence ───────────────
def test_le_journalier_passe_devant_le_funding_meme_s_il_manque_moins():
    # Cas reel du 15/11 : il manquait moins de prix journaliers que de funding, et le funding est
    # parti en premier. C'est l'inverse qu'il faut.
    plan = RP.ordonner({"bougies-1d": RP.besoin(300.0, 1), "funding-profond": RP.besoin(100_000.0, 1)})
    noms = [x["nom"] for x in plan]
    assert noms[0] == "bougies-1d", (
        f"ordre obtenu {noms} : le funding profond ne mesure rien sans un prix en face, et il "
        "coute 50 fois plus cher par jour gagne")


def test_la_precedence_passe_avant_le_rendement():
    """Meme avec un rendement meilleur, le funding ne peut pas devancer le prix dont il depend."""
    plan = RP.ordonner({"funding-profond": RP.besoin(20.0, 1), "bougies-1d": RP.besoin(100_000.0, 1)})
    noms = [x["nom"] for x in plan]
    assert noms.index("bougies-1d") < noms.index("funding-profond")


def test_une_tache_sans_manque_est_ecartee_du_plan():
    plan = RP.ordonner({"bougies-1d": RP.besoin(0.0, 1), "bougies-1h": RP.besoin(50.0, 1), "funding-profond": RP.besoin(0.0, 1)})
    assert [x["nom"] for x in plan] == ["bougies-1h"], (
        "on ne depense pas une requete pour verifier ce que l'etat dit deja")


def test_le_plan_porte_le_pourquoi_de_chaque_tache():
    plan = RP.ordonner({t.nom: RP.besoin(100.0, 1) for t in RP.TACHES})
    assert all(x["pourquoi"] for x in plan), "une tache sans justification n'a rien a faire ici"
    assert len(plan) == len(RP.TACHES)


# ─────────────── le budget : servir en entier plutot qu'un peu partout ───────────────
def test_le_budget_sert_les_premieres_taches_en_ENTIER():
    # 1 requete pour le journalier (un coin a rattraper), 4 800 pages pour le funding profond.
    plan = RP.ordonner({"bougies-1d": RP.besoin(1100.0, 1),
                        "funding-profond": RP.besoin(100_000.0, 4800)})
    reparti = RP.repartir_budget(plan, total_s=200.0)
    premier = reparti[0]
    assert premier["sert"] and premier["budget_s"] == pytest.approx(premier["cout_s"]), (
        "la premiere tache est servie en entier : une profondeur a moitie prise ne se mesure pas "
        "mieux qu'une profondeur absente")
    assert reparti[1]["budget_s"] == pytest.approx(200.0 - premier["cout_s"])
    assert reparti[1]["note"].startswith("budget partiel")


def test_une_miette_de_budget_ne_demarre_pas_une_tache_pour_rien():
    plan = RP.ordonner({"bougies-1d": RP.besoin(1100.0, 1),
                        "funding-profond": RP.besoin(100_000.0, 4800)})
    reparti = RP.repartir_budget(plan, total_s=plan[0]["cout_s"] + 5.0, minimum_s=60.0)
    assert reparti[0]["sert"] is True
    assert reparti[1]["sert"] is False and "minimum utile" in reparti[1]["note"]


def test_budget_nul_ne_sert_rien_mais_ne_perd_aucune_tache():
    plan = RP.ordonner({t.nom: RP.besoin(100.0, 1) for t in RP.TACHES})
    reparti = RP.repartir_budget(plan, total_s=0.0)
    assert len(reparti) == len(plan) and not any(x["sert"] for x in reparti)
    assert all("budget epuise" in x["note"] for x in reparti)


# ─────────────── la concurrence : 1, et pas « 1 sauf si tout va bien » ───────────────
def test_une_seule_tache_a_la_fois_quel_que_soit_le_niveau_de_memoire():
    for niveau in ("VERT", "ORANGE", "ROUGE", "n'importe quoi"):
        assert RP.concurrence(niveau_ram=niveau) == 1, (
            "les deux passes du 15/11 ont ete TUEES pour manque de memoire ; une passe tuee rend "
            "zero, donc sequentiel deux fois plus lent reste infiniment plus rapide")


def test_manques_lit_l_etat_des_collecteurs_tel_qu_il_est_ecrit():
    etat = {"1d": {"BTC": NOW - JOUR}, "funding": {"BTC": NOW - JOUR},
            "funding_ancien": {"BTC": NOW - 211 * JOUR}}
    out = RP.manques(coins=["BTC", "ETH"], etat=etat, now_ms=NOW)
    assert set(out) == {t.nom for t in RP.TACHES}
    assert out["funding-profond"]["jours_coins"] == pytest.approx((1100 - 211 + 1) + 1100, abs=1.0), (
        "BTC : 889 j a creuser + 1 j de retard ; ETH : jamais vu, 1 100 j")
    assert out["bougies-1d"]["jours_coins"] > 1100.0, "ETH n'a aucune bougie journaliere"


def test_eta_en_heures_additionne_les_couts():
    # 261 coins a creuser de 889 jours = 43 pages de 20,8 j chacun, soit 11 223 requetes.
    pages = 261 * 43
    plan = RP.ordonner({"funding-profond": RP.besoin(261 * 889.0, pages)})
    heures = RP.eta_heures(plan)
    assert 80.0 < heures < 130.0, (
        f"{heures:.0f} h : l'estimation doit retomber sur les ~107 h mesurees le 15/11 pour "
        "261 coins a creuser de 889 jours au debit historique de 100 u/min")


def test_le_cout_des_bougies_se_COMPTE_par_coin_et_non_par_jours_manquants():
    """L'erreur de x87 du 15/11, verrouillee.

    Mesure reelle : 261 coins sur 261 avaient au moins un jour de retard sur le pas journalier,
    donc **261 requetes**. L'ancien modele divisait 10 491 jours-coins manquants par 5 000 jours
    par requete et annoncait **3 requetes, 3 minutes** — le budget alloue a la tache etait donc
    87 fois trop court, et elle s'arretait apres 3 coins.
    """
    etat = {c: NOW - 2 * JOUR for c in (f"C{i}" for i in range(261))}
    mesure = RP.manque_bougies(coins=list(etat), etat_serie=etat, profondeur_j=5000.0,
                               now_ms=NOW, pas_ms=RP.JOUR_MS)
    assert mesure["requetes"] == 261, (
        "un coin en retard de 2 jours coute une requete ENTIERE, pas 2/5 000e de requete")
    assert mesure["jours_coins"] == pytest.approx(522.0, abs=1.0)
    cout = RP.TACHES_PAR_NOM["bougies-1d"].cout_s(mesure["requetes"], budget_par_minute=100.0)
    assert cout > 4.0 * 3600.0, f"{cout / 3600:.1f} h : 261 requetes a 62 s, pas 3 minutes"


def test_un_coin_a_jour_a_moins_d_un_pas_de_retard_et_ne_coute_rien():
    etat = {"BTC": NOW - 1000}                       # une seconde de retard
    mesure = RP.manque_bougies(coins=["BTC"], etat_serie=etat, profondeur_j=208.0, now_ms=NOW,
                               pas_ms=RP.HEURE_MS)
    assert mesure["requetes"] == 0, (
        "sans bougie close nouvelle, la requete rendrait une liste vide : on ne la fait pas")
