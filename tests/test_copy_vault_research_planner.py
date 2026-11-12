"""Planificateur de recherche : classe les hypothèses du registre, sans jamais promouvoir quoi que ce soit."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from hl_observer.backtesting import copy_vault_research_planner as P

RACINE = Path(__file__).resolve().parents[1]


def _replication(statut, net, intervalle, jours, run="r1"):
    return {"run_id": run, "evidence_tier": "T", "summary": {"net_usd_per_day": net, "interval_95": intervalle,
                                                              "distinct_days": jours},
            "verdicts": [{"hypothesis": "copy_vault_slow_replication_350usd", "status": statut, "reason": "x"}]}


def _ouvertures(statut, net_bps, intervalle, jours, usd):
    return {"run_id": "o1", "evidence_tier": "T", "config": {"min_days": 30},
            "primary": {"net": {"moyenne_bps": net_bps, "intervalle_bps": intervalle, "jours": jours},
                        "niveau_intervalle": 0.95},
            "capital_350": {"net_usd_par_jour": usd},
            "verdicts": [{"hypothesis": "copy_vault_aggressive_open_drift", "status": statut, "reason": "x"}]}


def _ligne(plan, hypothese):
    return next(h for h in plan["hypotheses"] if h["hypothesis"] == hypothese)


def test_un_effet_net_et_precis_passe_devant_un_effet_flou_et_un_rejet_ne_recoit_plus_rien():
    registre = [
        _replication("MORE_DATA", 0.80, [-3.0, 4.6], 10),                    # gros effet apparent, très flou
        _ouvertures("MORE_DATA", 12.0, [2.0, 22.0], 20, 0.40),               # effet plus petit, bien mesuré
        {"run_id": "m1", "verdicts": [{"hypothesis": "copy_vault_naive_mirror_taker", "status": "REJECTED",
                                       "reason": "perd après coûts"}]},
    ]
    plan = P.build_plan(registre)
    ordre = [h["hypothesis"] for h in plan["hypotheses"]]
    assert ordre == ["copy_vault_aggressive_open_drift", "copy_vault_slow_replication_350usd",
                     "copy_vault_naive_mirror_taker"]
    assert plan["prochaine_action"] == "copy_vault_aggressive_open_drift"
    net, flou, rejet = (_ligne(plan, h) for h in ordre)
    assert net["p_positif"] > 0.98 and flou["p_positif"] == pytest.approx(0.66, abs=0.02)
    # l'a priori sceptique ramène vers zéro l'effet mal mesuré bien plus que l'effet bien mesuré
    assert flou["usd_par_jour_sceptique"] < 0.25 * flou["usd_par_jour"]
    assert net["usd_par_jour_sceptique"] > 0.85 * net["usd_par_jour"]
    assert net["p_positif_sceptique"] <= net["p_positif"] and flou["p_positif_sceptique"] <= flou["p_positif"]
    assert rejet["priorite"] == 0.0 and rejet["action"].startswith("abandonner")
    assert plan["resume"] == {"PROVEN": 0, "PROMISING": 0, "MORE_DATA": 2, "UNMEASURABLE": 0, "REJECTED": 1}
    assert plan["economically_proven"] is False


def test_jours_restants_le_plus_exigeant_de_l_etude_et_de_la_statistique():
    # 10 jours mesurés ; intervalle de demi-largeur 3,8 pour un effet de 0,8 : il faudrait (3,8/0,8)^2 fois plus
    plan = P.build_plan([_replication("MORE_DATA", 0.80, [-3.0, 4.6], 10)])
    ligne = _ligne(plan, "copy_vault_slow_replication_350usd")
    assert ligne["jours_pour_trancher"] == pytest.approx(10 * (3.8 / 0.8) ** 2, rel=0.02)
    assert ligne["jours_requis"] == 20 and ligne["jours_restants"] == ligne["jours_pour_trancher"] - 10
    assert "attendre environ" in ligne["action"]
    # effet déjà net : seule l'exigence de l'étude (30 jours) reste
    net = _ligne(P.build_plan([_ouvertures("MORE_DATA", 12.0, [9.0, 15.0], 20, 0.4)]), "copy_vault_aggressive_open_drift")
    assert net["jours_pour_trancher"] <= 20 and net["jours_restants"] == 10
    # plus de données rapproche la décision : la priorité monte quand l'attente baisse
    proche = _ligne(P.build_plan([_ouvertures("MORE_DATA", 12.0, [9.0, 15.0], 29, 0.4)]), "copy_vault_aggressive_open_drift")
    assert proche["jours_restants"] == 1 and proche["priorite"] > net["priorite"]


def test_seul_le_dernier_enregistrement_compte_et_un_effet_negatif_n_a_aucune_priorite():
    plan = P.build_plan([_replication("MORE_DATA", 0.8, [0.2, 1.4], 25, run="ancien"),
                         _replication("MORE_DATA", -0.5, [-1.1, 0.1], 40, run="recent")])
    ligne = _ligne(plan, "copy_vault_slow_replication_350usd")
    assert ligne["run_id"] == "recent" and ligne["essais_enregistres"] == 2
    assert ligne["priorite"] == 0.0 and ligne["p_positif"] < 0.1 and plan["prochaine_action"] is None


def test_non_mesurable_et_hypothese_inconnue_ne_sont_ni_inventees_ni_oubliees():
    registre = [
        {"run_id": "x", "inputs": {"jours": 0}, "config": {"min_days": 5},
         "verdicts": [{"hypothesis": "copy_vault_leader_order_intent", "status": "UNMEASURABLE", "reason": "aucun carnet"}]},
        {"run_id": "y", "verdicts": [{"hypothesis": "hypothese_sans_extracteur", "status": "PROMISING", "reason": "z"}]},
        _replication("MORE_DATA", None, None, 3),
    ]
    plan = P.build_plan(registre)
    assert {h["hypothesis"] for h in plan["hypotheses"]} == {
        "copy_vault_leader_order_intent", "hypothese_sans_extracteur", "copy_vault_slow_replication_350usd"}
    ordres = _ligne(plan, "copy_vault_leader_order_intent")
    assert ordres["effet"] is None and ordres["priorite"] == 0.0 and "activer la collecte" in ordres["action"]
    inconnue = _ligne(plan, "hypothese_sans_extracteur")
    assert inconnue["effet"] is None and inconnue["priorite"] == 0.0 and "geler le candidat" in inconnue["action"]
    sans_mesure = _ligne(plan, "copy_vault_slow_replication_350usd")
    assert sans_mesure["p_positif"] is None and sans_mesure["jours_restants"] == 17
    texte = P.render_plan(plan)
    assert all(h["hypothesis"] in texte for h in plan["hypotheses"]) and "ne promeut aucun candidat" in texte
    assert P.build_plan(registre) == plan                                         # déterministe
    assert P.build_plan([])["hypotheses"] == [] and P.build_plan([])["prochaine_action"] is None


def test_l_outil_ecrit_le_plan_depuis_le_registre_verifie(tmp_path):
    spec = importlib.util.spec_from_file_location("etude_copiabilite", RACINE / "tools" / "etude_copiabilite.py")
    etude = importlib.util.module_from_spec(spec)
    sys.modules["etude_copiabilite"] = etude
    spec.loader.exec_module(etude)
    dossier = tmp_path / etude.REPORT_DIR
    dossier.mkdir(parents=True)
    for enregistrement in (_replication("MORE_DATA", 0.80, [-3.0, 4.6], 10), _ouvertures("MORE_DATA", 12.0, [2.0, 22.0], 20, 0.4)):
        etude.append_ledger(dossier / "EXPERIENCES.ndjson", enregistrement)
    plan = etude.run_plan(tmp_path)
    assert plan["prochaine_action"] == "copy_vault_aggressive_open_drift"
    assert json.loads((dossier / "PLAN_DE_RECHERCHE.json").read_text(encoding="utf-8"))["hypotheses"] == plan["hypotheses"]
    assert "Plan de recherche Copy-Vault" in (dossier / "PLAN_DE_RECHERCHE.md").read_text(encoding="utf-8")
    # registre altéré : aucun plan n'est tiré d'une chaîne qui ne se vérifie pas
    contenu = (dossier / "EXPERIENCES.ndjson").read_text(encoding="utf-8").replace("0.8", "9.9", 1)
    (dossier / "EXPERIENCES.ndjson").write_text(contenu, encoding="utf-8")
    assert etude.run_plan(tmp_path)["status"] == "REGISTRE_NON_VERIFIE"


def test_lecture_en_quatre_cas_et_on_n_attend_pas_des_annees():
    """Cas réel du 2026-11-11 : 602 jours mesurés, effet -2 bps/jour, il faudrait 10 946 jours pour trancher."""
    persistance = {"run_id": "p", "config": {"period_days": [7], "min_dates": 12},
                   "primary": {"exces_tete_bps_jour": -2.06, "exces_tete_intervalle_bps_jour": [-17.21, 11.56],
                               "niveau_intervalle": 0.9982, "dates": 86},
                   "verdicts": [{"hypothesis": "copy_vault_leader_skill_persistence", "status": "MORE_DATA", "reason": "x"}]}
    plan = P.build_plan([
        persistance,
        _ouvertures("MORE_DATA", -26.9, [-30.8, -23.2], 4, -2.98),          # négatif mais 4 jours : insuffisant
        {"run_id": "s", "verdicts": [{"hypothesis": "hypothese_sans_extracteur", "status": "MORE_DATA", "reason": "x"}]},
        _replication("PROMISING", 0.8, [0.3, 1.3], 30),
        {"run_id": "m", "verdicts": [{"hypothesis": "copy_vault_naive_mirror_taker", "status": "REJECTED", "reason": "x"}]},
    ])
    lectures = {h["hypothesis"]: h["lecture"] for h in plan["hypotheses"]}
    assert lectures == {
        "copy_vault_slow_replication_350usd": "SIGNAL_PROMETTEUR",
        "copy_vault_aggressive_open_drift": "DONNEES_INSUFFISANTES",
        "hypothese_sans_extracteur": "DONNEES_INSUFFISANTES",                 # rien d'inventé
        "copy_vault_leader_skill_persistence": "ABSENCE_D_AVANTAGE_DEMONTRE",
        "copy_vault_naive_mirror_taker": "ABSENCE_D_AVANTAGE_DEMONTRE",
    }
    sans_fin = _ligne(plan, "copy_vault_leader_skill_persistence")
    assert sans_fin["jours_pour_trancher"] > 5_000 and sans_fin["action"].startswith("ne pas attendre")
    # ordre : priorité, puis ce qui peut encore apprendre le plus vite ; l'absence d'avantage ferme la marche
    ordre = [h["hypothesis"] for h in plan["hypotheses"]]
    assert ordre[0] == "copy_vault_slow_replication_350usd"
    assert ordre.index("copy_vault_aggressive_open_drift") < ordre.index("copy_vault_leader_skill_persistence")
    assert set(ordre[-2:]) == {"copy_vault_leader_skill_persistence", "copy_vault_naive_mirror_taker"}
    fragile = P.build_plan([_ouvertures("MORE_DATA", 12.0, [9.0, 15.0], 20, 0.4)])["hypotheses"][0]
    assert fragile["lecture"] == "SIGNAL_FRAGILE"                             # net et précis, mais pas encore 30 jours
    assert "signal fragile" in P.render_plan(P.build_plan([_ouvertures("MORE_DATA", 12.0, [9.0, 15.0], 20, 0.4)]))


def test_la_selection_de_leaders_est_lue_par_le_planificateur():
    record = {"run_id": "o2", "config": {"min_days": 30},
              "selection": {"primaire": {"retenus": {"net": {"moyenne_bps": 15.0, "intervalle_bps": [4.0, 26.0], "jours": 35},
                                                     "niveau_intervalle": 0.95},
                                         "capital_350": {"esperance_usd_par_jour": 0.9}}},
              "verdicts": [{"hypothesis": "copy_vault_aggressive_open_selected_leaders", "status": "PROMISING", "reason": "x"}]}
    ligne = P.build_plan([record])["hypotheses"][0]
    assert ligne["effet"] == 15.0 and ligne["usd_par_jour"] == 0.9 and ligne["lecture"] == "SIGNAL_PROMETTEUR"
    assert ligne["p_positif"] > 0.99 and ligne["priorite"] > 0
