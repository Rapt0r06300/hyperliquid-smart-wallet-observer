"""La conduite du labo par tranches : découper d'après la densité réelle, ne rien fabriquer.

Les six journées du corpus sont inégales — 2 172 496 fills le 13/11 contre 476 078 le 18/11 — donc
un découpage calendaire donnerait une tranche de ~7 Go et une de ~1,5 Go. Ces tests verrouillent le
découpage par densité, la contiguïté des tranches, et le refus de transformer une tranche en échec
silencieux.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting import agregation_tranches as AG
from tools import conduire_labo_par_tranches as CD

HEURE = 3_600_000


def _ruban(tmp_path, fills_par_heure):
    """Un ruban où l'heure `i` porte `n` fills."""
    chemin = tmp_path / "runtime" / "data" / "vault_fills_live.jsonl"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        for heure, nombre in enumerate(fills_par_heure):
            for index in range(nombre):
                flux.write(json.dumps({"ts_ms": (heure + 1) * HEURE + index, "coin": "BTC"}) + "\n")
    return chemin


# ───────────────────────── la mesure de densité ─────────────────────────

def test_la_densite_est_mesuree_PAR_PAS_de_temps(tmp_path):
    ruban = _ruban(tmp_path, [3, 0, 5])
    densite = CD.densite_par_pas(ruban)
    assert sorted(densite.values()) == [3, 5], "l'heure vide n'apparaît pas"
    assert len(densite) == 2


def test_un_ruban_ABSENT_rend_une_densite_vide_sans_lever(tmp_path):
    """Et c'est l'appelant qui décide : `main` rend 2 et dit que ce n'est pas un zéro."""
    assert CD.densite_par_pas(tmp_path / "jamais.jsonl") == {}


def test_une_ligne_SANS_horodatage_est_ignoree_pas_comptee_a_zero(tmp_path):
    chemin = tmp_path / "r.jsonl"
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        flux.write('{"coin":"BTC"}\n')
        flux.write(json.dumps({"ts_ms": HEURE, "coin": "BTC"}) + "\n")
    assert sum(CD.densite_par_pas(chemin).values()) == 1


# ───────────────────────── le découpage ─────────────────────────

def test_le_decoupage_respecte_le_budget_de_lignes():
    densite = {HEURE: 400, 2 * HEURE: 400, 3 * HEURE: 400}
    tranches = CD.decouper(densite, budget=500)
    assert len(tranches) == 3, "400 + 400 dépasse 500 : chaque heure va dans sa tranche"


def test_des_pas_legers_sont_REGROUPES():
    densite = {HEURE: 100, 2 * HEURE: 100, 3 * HEURE: 100}
    tranches = CD.decouper(densite, budget=500)
    assert len(tranches) == 1 and tranches[0] == (HEURE, 4 * HEURE - 1)


def test_les_tranches_sont_CONTIGUES_sans_trou_ni_recouvrement():
    """Le contrôle qui compte : c'est `couverture` qui le dira à l'agrégat."""
    densite = {h * HEURE: 300 for h in range(1, 8)}
    tranches = CD.decouper(densite, budget=500)
    assert len(tranches) > 1
    couv = AG.couverture(tranches)
    assert couv["continue"] is True, couv
    assert couv["trous"] == [] and couv["recouvrements"] == []


def test_un_pas_SEUL_au_dessus_du_budget_est_rendu_tel_quel():
    """Le casser séparerait des fills que la reconstruction doit voir ensemble."""
    tranches = CD.decouper({HEURE: 10_000}, budget=500)
    assert tranches == [(HEURE, 2 * HEURE - 1)], "une tranche lourde vaut mieux qu'un mensonge"


def test_une_densite_vide_ne_donne_AUCUNE_tranche():
    assert CD.decouper({}) == []


def test_les_pas_non_contigus_restent_couverts_sans_trou():
    """Un trou d'activité ne doit pas devenir un trou de COUVERTURE."""
    tranches = CD.decouper({HEURE: 100, 5 * HEURE: 100}, budget=500)
    assert AG.couverture(tranches)["continue"] is True


# ───────────────────────── la conduite ─────────────────────────

def test_chaque_tranche_est_lancee_UNE_fois_avec_ses_bornes(tmp_path):
    vues = []

    def lancer(_ws, tranche):
        vues.append(tranche)
        return {"status": "MORE_DATA", "net_pnl_usd": 1.0}

    tranches = [(1, HEURE), (HEURE + 1, 2 * HEURE)]
    resultat = CD.conduire(tmp_path, tranches, lancer=lancer, additifs=("net_pnl_usd",))
    assert vues == tranches
    assert resultat["agregat"]["totaux"]["net_pnl_usd"]["total"] == 2.0
    assert resultat["agregat"]["exploitable"] is True


def test_la_tranche_est_REPORTEE_dans_chaque_rapport(tmp_path):
    resultat = CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
    )
    assert resultat["rapports"][0]["tranche"] == [1, HEURE]


def test_une_tranche_qui_LEVE_est_consignee_et_ne_devient_pas_un_zero(tmp_path):
    def lancer(_ws, tranche):
        if tranche[0] == 1:
            raise MemoryError("plus de place")
        return {"status": "MORE_DATA", "net_pnl_usd": 5.0}

    resultat = CD.conduire(
        tmp_path, [(1, HEURE), (HEURE + 1, 2 * HEURE)],
        lancer=lancer, additifs=("net_pnl_usd",),
    )
    assert resultat["incidents"][0]["erreur"] == "MemoryError"
    assert resultat["incidents"][0]["message"] == "plus de place"
    agregat = resultat["agregat"]
    assert agregat["exploitable"] is False
    assert agregat["raison_non_exploitable"] == "TRANCHE_SANS_RAPPORT"
    assert agregat["totaux"]["net_pnl_usd"]["total"] == 5.0, "le total reste lisible…"
    assert agregat["totaux"]["net_pnl_usd"]["complet"] is False, "…mais il est déclaré incomplet"


def test_un_rapport_NON_LISIBLE_est_refuse_comme_un_echec(tmp_path):
    resultat = CD.conduire(tmp_path, [(1, HEURE)], lancer=lambda _w, _t: "tout va bien")
    assert resultat["incidents"][0]["erreur"] == "RAPPORT_NON_LISIBLE"
    assert resultat["agregat"]["exploitable"] is False


def test_TOUTES_les_tranches_sont_tentees_meme_apres_un_echec(tmp_path):
    """Un échec au milieu ne doit pas priver les suivantes de leur mesure."""
    vues = []

    def lancer(_ws, tranche):
        vues.append(tranche[0])
        if tranche[0] == HEURE + 1:
            raise RuntimeError("au milieu")
        return {"status": "MORE_DATA"}

    CD.conduire(
        tmp_path,
        [(1, HEURE), (HEURE + 1, 2 * HEURE), (2 * HEURE + 1, 3 * HEURE)],
        lancer=lancer,
    )
    assert vues == [1, HEURE + 1, 2 * HEURE + 1]


def test_le_verdict_le_plus_faible_remonte_a_la_conduite(tmp_path):
    etats = iter(("PROVEN", "UNMEASURABLE"))
    resultat = CD.conduire(
        tmp_path, [(1, HEURE), (HEURE + 1, 2 * HEURE)],
        lancer=lambda _w, _t: {"status": next(etats)},
    )
    assert resultat["agregat"]["verdict"]["status"] == "UNMEASURABLE"


def test_la_conduite_est_PAPER_et_le_declare(tmp_path):
    resultat = CD.conduire(tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"})
    assert resultat["paper_read_only"] is True and resultat["real_execution"] is False
    assert resultat["schema"] == CD.SCHEMA


# ───────────────────────── la ligne de commande ─────────────────────────

def test_le_mode_plan_seulement_ne_lance_PAS_le_labo(tmp_path, capsys, monkeypatch):
    _ruban(tmp_path, [50, 50])

    def interdit(*_a, **_k):
        raise AssertionError("le labo ne doit pas tourner en mode plan")

    monkeypatch.setattr(CD, "_lanceur_reel", interdit)
    assert CD.main([str(tmp_path), "--plan-seulement", "--budget", "1000"]) == 0
    sortie = capsys.readouterr().out
    assert "100 fills" in sortie and "1 tranches" in sortie
    assert "continue=True" in sortie


def test_un_ruban_vide_rend_un_code_D_ERREUR_pas_un_succes(tmp_path, capsys):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_fills_live.jsonl").write_text("", encoding="utf-8")
    assert CD.main([str(tmp_path), "--plan-seulement"]) == 2
    assert "ce n'est pas un zéro" in capsys.readouterr().out


def test_le_plan_SIGNALE_une_tranche_au_dessus_du_budget(tmp_path, capsys):
    _ruban(tmp_path, [900])
    CD.main([str(tmp_path), "--plan-seulement", "--budget", "100"])
    assert "au-dessus du budget" in capsys.readouterr().out


@pytest.mark.parametrize("heures", (1, 3))
def test_le_pas_de_decoupage_est_reglable(tmp_path, heures):
    _ruban(tmp_path, [10, 10, 10])
    densite = CD.densite_par_pas(
        tmp_path / "runtime" / "data" / "vault_fills_live.jsonl", pas_ms=heures * HEURE)
    assert sum(densite.values()) == 30
    assert len(densite) == (3 if heures == 1 else 2)
# ───────────────────── la garde mémoire : jamais de crash, jamais de zéro ─────────────────────
# Une tranche pèse ~2,5 Go. Enchaîner dix-neuf tranches sans regarder la mémoire reproduirait
# exactement ce qui a fait couper le rejeu. Le gouverneur est injecté pour tester sans pression
# réelle : une garde qu'on ne peut déclencher à volonté n'est pas une garde vérifiée.

from hl_observer.ops import budget_ram as RAM


def _avis(action, raison="essai"):
    return {"action": action, "niveau": "ROUGE" if action == RAM.PAUSER else "VERT",
            "facteur": 1.0, "raison": raison}


def test_en_RAM_SAINE_la_tranche_part_sans_attendre(tmp_path):
    souffles = []
    resultat = CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
        gouverneur=lambda **_k: _avis(RAM.CONTINUER),
        respirer=lambda: souffles.append(1) or {},
    )
    assert souffles == [] and len(resultat["rapports"]) == 1


def test_en_RAM_CRITIQUE_on_SOUFFLE_puis_on_lance_si_ca_s_est_degage(tmp_path):
    """La dégradation est progressive : on ne renonce pas au premier signal rouge."""
    avis = iter((_avis(RAM.PAUSER), _avis(RAM.CONTINUER)))
    souffles = []
    resultat = CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
        gouverneur=lambda **_k: next(avis),
        respirer=lambda: souffles.append(1) or {"attendu_s": 12.0},
    )
    assert len(souffles) == 1, "on a bien attendu"
    assert len(resultat["rapports"]) == 1 and resultat["incidents"] == []


def test_si_la_RAM_reste_critique_la_tranche_est_NON_EVALUEE_jamais_un_zero(tmp_path):
    resultat = CD.conduire(
        tmp_path, [(1, HEURE), (HEURE + 1, 2 * HEURE)],
        lancer=lambda _w, _t: {"status": "MORE_DATA", "net_pnl_usd": 3.0},
        gouverneur=lambda **_k: _avis(RAM.PAUSER, "RAM critique (0.4 Go libres)"),
        respirer=lambda: {"attendu_s": 30.0},
        additifs=("net_pnl_usd",),
    )
    assert len(resultat["incidents"]) == 2
    assert resultat["incidents"][0]["erreur"] == "MEMOIRE_INSUFFISANTE"
    assert "0.4 Go" in resultat["incidents"][0]["message"]
    assert resultat["incidents"][0]["apres_attente_s"] == 30.0
    assert resultat["agregat"]["exploitable"] is False
    total = resultat["agregat"]["totaux"]["net_pnl_usd"]
    assert total["total"] == 0 and total["complet"] is False, "aucun rapport : rien n'est affirmé"


def test_une_tranche_refusee_n_empeche_pas_les_SUIVANTES(tmp_path):
    """La mémoire peut se libérer entre deux tranches : renoncer à tout serait excessif."""
    avis = iter((_avis(RAM.PAUSER), _avis(RAM.PAUSER), _avis(RAM.CONTINUER)))
    lancees = []
    resultat = CD.conduire(
        tmp_path, [(1, HEURE), (HEURE + 1, 2 * HEURE)],
        lancer=lambda _w, t: lancees.append(t[0]) or {"status": "MORE_DATA"},
        gouverneur=lambda **_k: next(avis),
        respirer=lambda: {"attendu_s": 1.0},
    )
    assert lancees == [HEURE + 1], "la 1ʳᵉ est refusée, la 2ᵈ part"
    assert len(resultat["incidents"]) == 1 and len(resultat["rapports"]) == 1


def test_le_BESOIN_estime_est_transmis_au_gouverneur(tmp_path):
    """Sans besoin estimé, le gouverneur ne peut pas refuser un bloc trop gros en RAM saine."""
    vus = []
    CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
        estimation=lambda _t: 7_000_000_000,
        gouverneur=lambda **kw: vus.append(kw.get("besoin_octets")) or _avis(RAM.CONTINUER),
    )
    assert vus == [7_000_000_000]


def test_SANS_estimation_le_gouverneur_est_consulte_quand_meme(tmp_path):
    vus = []
    CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
        gouverneur=lambda **kw: vus.append(kw.get("besoin_octets")) or _avis(RAM.CONTINUER),
    )
    assert vus == [None], "l'état mémoire se lit même sans besoin annoncé"


def test_la_memoire_consommee_est_PUBLIEE_par_tranche(tmp_path):
    resultat = CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
        estimation=lambda _t: 1_000,
        gouverneur=lambda **_k: _avis(RAM.CONTINUER),
    )
    ligne = resultat["memoire_par_tranche"][0]
    assert ligne["tranche"] == [1, HEURE] and ligne["besoin_estime_octets"] == 1_000
    assert ligne["niveau_avant"] == "VERT" and "octets_consommes" in ligne


def test_une_tranche_REFUSEE_n_apparait_pas_dans_la_memoire_par_tranche(tmp_path):
    resultat = CD.conduire(
        tmp_path, [(1, HEURE)], lancer=lambda _w, _t: {"status": "MORE_DATA"},
        gouverneur=lambda **_k: _avis(RAM.PAUSER), respirer=lambda: {},
    )
    assert resultat["memoire_par_tranche"] == [], "rien n'a tourné, rien à mesurer"


def test_le_gouverneur_REEL_est_le_defaut():
    import inspect

    signature = inspect.signature(CD.conduire)
    assert signature.parameters["gouverneur"].default is RAM.decision
    assert signature.parameters["respirer"].default is RAM.attendre_que_ca_respire


def test_l_estimation_de_la_CLI_suit_la_densite_mesuree(tmp_path, capsys, monkeypatch):
    """Le besoin annoncé doit venir de la densité réelle, pas d'une moyenne supposée."""
    _ruban(tmp_path, [1_000])
    vus = []

    def faux_lanceur(*_a, **_k):
        return lambda _w, _t: {"status": "MORE_DATA"}

    monkeypatch.setattr(CD, "_lanceur_reel", faux_lanceur)
    monkeypatch.setattr(CD, "conduire", lambda *a, **kw: vus.append(kw.get("estimation")) or {
        "agregat": {"verdict": {"status": "MORE_DATA"}, "exploitable": True,
                    "jours": {"distincts": 1}},
        "incidents": [],
    })
    CD.main([str(tmp_path), "--budget", "5000"])
    estimer = vus[0]
    assert estimer is not None
    attendu = int(1_000 * CD.OCTETS_PAR_FILL * CD.FACTEUR_CARNETS)
    assert estimer((HEURE, 2 * HEURE - 1)) == attendu
def test_le_facteur_des_carnets_COUVRE_le_maximum_mesure():
    """Une garde mémoire doit se tromper vers le HAUT, jamais vers le bas.

    Mesure du 18/11/2026 sur les 129 heures du corpus (rapport des octets carnets/fills) :
    médiane 0,70, p90 1,03, max 1,39 — soit un facteur `1 + rapport` allant jusqu'à 2,39. Mon
    premier choix, 1,8, était déduit de la seule journée du 18/11 et sous-estimait le besoin une
    heure sur dix : la garde aurait laissé partir une tranche qu'elle croyait légère.
    """
    assert CD.FACTEUR_CARNETS >= 2.39, (
        "le facteur doit couvrir le pire rapport mesuré, pas le rapport médian")


def test_l_estimation_depasse_le_poids_des_seuls_fills():
    """Le contrôle minimal : estimer le besoin d'une tranche sans ses carnets serait absurde."""
    lignes = 100_000
    estime = lignes * CD.OCTETS_PAR_FILL * CD.FACTEUR_CARNETS
    assert estime > lignes * CD.OCTETS_PAR_FILL
    assert CD.OCTETS_PAR_FILL == 3_754, "octets par fill mesurés le 18/11 (400 000 lignes = 1,50 Go)"
# ───────── les journées du corpus, mesurées et transmises ─────────

def test_les_journees_UTC_sont_comptees_depuis_la_densite_mesuree(tmp_path):
    _ruban(tmp_path, [10, 10, 10])
    densite = CD.densite_par_pas(tmp_path / "runtime" / "data" / "vault_fills_live.jsonl")
    jours = CD.journees_utc(densite)
    assert len(jours) == 1 and jours[0].count("-") == 2, "trois heures de la même journée"


def test_un_pas_VIDE_ne_cree_pas_une_journee():
    """Un seau à zéro ne doit pas gonfler le compte des journées : il n'y a rien à évaluer."""
    assert CD.journees_utc({0: 0, 86_400_000: 5}) == ["1970-01-02"]


def test_des_journees_DISTINCTES_sont_toutes_comptees():
    densite = {jour * 86_400_000 + 3_600_000: 7 for jour in range(6)}
    assert len(CD.journees_utc(densite)) == 6


def test_le_lanceur_transmet_les_journees_du_corpus_au_labo(tmp_path, monkeypatch):
    import hl_observer.backtesting.copy_vault_local_lab as module

    vues = []
    monkeypatch.setattr(
        module, "run_local_campaign",
        lambda _w, **kw: vues.append(kw.get("jours_du_corpus")) or {"status": "MORE_DATA"})
    CD._lanceur_reel(1, tmp_path / "c", tmp_path, jours_du_corpus=6)(tmp_path, (1, 2))
    assert vues == [6]


def test_le_seuil_du_conducteur_est_CELUI_du_labo_pas_une_copie():
    """Une constante recopiée finit par diverger : on importe la valeur du labo."""
    from hl_observer.backtesting.copy_vault_local_lab import _MINIMUM_SIGNAL_UTC_DAYS

    assert CD.JOURS_MINIMUM == _MINIMUM_SIGNAL_UTC_DAYS == 6


def test_la_conduite_transmet_le_seuil_a_l_agregat(tmp_path):
    """Sinon le déplacement de la porte serait un desserrage sans contrepartie."""
    resultat = CD.conduire(
        tmp_path, [(1, HEURE)], jours_minimum=6,
        lancer=lambda _w, _t: {"status": "MORE_DATA",
                               "signal_coverage": {"utc_days": ["2026-11-13"]}},
    )
    agregat = resultat["agregat"]
    assert agregat["jours_minimum"] == 6 and agregat["exploitable"] is False
    assert agregat["raison_non_exploitable"] == "JOURNEES_INSUFFISANTES"
def test_le_rapport_AFFICHE_que_la_preuve_est_impossible(tmp_path, capsys, monkeypatch):
    """Une donnée publiée mais jamais affichée est une donnée invisible."""
    _ruban(tmp_path, [50])
    monkeypatch.setattr(CD, "_lanceur_reel", lambda *_a, **_k: (
        lambda _w, t: {"status": "PROMISING", "verdict_partiel": True, "candidates_tested": 9,
                       "signal_coverage": {"utc_days": ["2026-11-13"]}}))
    CD.main([str(tmp_path), "--budget", "1000"])
    sortie = capsys.readouterr().out
    assert "PREUVE IMPOSSIBLE" in sortie and "RAPPORTS_PARTIELS" in sortie
    assert "1 rapport(s) partiel(s) sur 1" in sortie
    assert "candidats essayés, toutes tranches : 9" in sortie
    assert "/ 6 requis" in sortie

