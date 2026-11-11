"""Budget de collecte piloté par le labo : classes de cadence du poll (lecture seule, PAPER)."""
from __future__ import annotations

import json

import tools.collecter_userfills_poll as P
from hl_observer.collection import forward_poll_fills as F

SLOW = "0x" + "a" * 40
BOT = "0x" + "b" * 40
CLONE = "0x" + "c" * 40
NEW = "0x" + "d" * 40

NEEDS = {
    "experiment_id": "exp-1",
    "leaders": [
        {"unit": SLOW, "addresses": [SLOW], "cadence": "PRIORITAIRE"},
        {"unit": BOT, "addresses": [BOT, CLONE.upper().replace("0X", "0x")], "cadence": "ARCHIVE"},
        {"unit": "0x" + "e" * 40, "addresses": [], "cadence": "CLASSE_INCONNUE"},
        {"unit": "pas-une-adresse", "cadence": "STANDARD"},
        "ligne invalide",
    ],
}


def test_cadence_plan_ignore_l_invalide_et_archive_les_clones():
    plan = F.cadence_plan(NEEDS)
    assert plan == {SLOW: "PRIORITAIRE", BOT: "ARCHIVE", CLONE: "ARCHIVE"}
    assert F.cadence_plan(None) == {} and F.cadence_plan({"leaders": "x"}) == {}


def test_clone_d_un_operateur_lent_passe_en_archive_pas_le_representant():
    plan = F.cadence_plan({"leaders": [{"unit": SLOW, "addresses": [SLOW, CLONE], "cadence": "PRIORITAIRE"}]})
    assert plan == {SLOW: "PRIORITAIRE", CLONE: "ARCHIVE"}


def test_class_interval_repartit_le_budget_sans_changer_l_historique_par_defaut():
    assert F.class_interval_s(5.0, 0, "ARCHIVE") == F.ARCHIVE_INTERVAL_S
    assert F.class_interval_s(5.0, 99, "ARCHIVE") == F.ARCHIVE_INTERVAL_S      # l'activité n'achète plus de budget
    assert F.class_interval_s(5.0, 0, "PRIORITAIRE") == F.PRIORITY_INTERVAL_S
    assert F.class_interval_s(5.0, 0, "STANDARD") == F.STANDARD_INTERVAL_S
    for count in (0, 3, 9):  # non classé ou classe inconnue : comportement historique exact
        assert F.class_interval_s(5.0, count, None) == F.adaptive_interval_s(5.0, count)
        assert F.class_interval_s(5.0, count, "DECOUVERTE") == F.adaptive_interval_s(5.0, count)
    # un plan complet coûte moins de requêtes qu'un suivi « tout adaptatif » des mêmes robots
    hft_per_min = 60.0 / F.adaptive_interval_s(5.0, 9)
    assert 60.0 / F.class_interval_s(5.0, 9, "ARCHIVE") < hft_per_min / 100


def test_charger_plan_cadence_trace_et_reste_optionnel(tmp_path, monkeypatch):
    monkeypatch.delenv("ALINA_POLL_CADENCE_LABO", raising=False)
    leaders = [SLOW, BOT, NEW]
    plan, audit = P.charger_plan_cadence(tmp_path, leaders)
    assert plan == {} and audit == {"applique": False, "raison": "plan_absent"}
    besoins = tmp_path / P.BESOINS_COLLECTE
    besoins.parent.mkdir(parents=True)
    besoins.write_text(json.dumps(NEEDS), encoding="utf-8")
    plan, audit = P.charger_plan_cadence(tmp_path, leaders)
    assert plan == {SLOW: "PRIORITAIRE", BOT: "ARCHIVE"}
    assert audit["applique"] and audit["experiment_id"] == "exp-1"
    assert audit["classes"] == {"ARCHIVE": 1, "PRIORITAIRE": 1} and audit["non_classes"] == 1
    P._journaliser_cadence(tmp_path, audit)
    ligne = json.loads((tmp_path / P.CADENCE_AUDIT).read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["experiment_id"] == "exp-1" and ligne["ts_ms"] > 0
    monkeypatch.setenv("ALINA_POLL_CADENCE_LABO", "0")
    assert P.charger_plan_cadence(tmp_path, leaders) == ({}, {"applique": False, "raison": "desactive_par_operateur"})
    besoins.write_text("{json cassé", encoding="utf-8")
    monkeypatch.delenv("ALINA_POLL_CADENCE_LABO")
    assert P.charger_plan_cadence(tmp_path, leaders)[0] == {}        # illisible : jamais bloquant


def test_echantillon_d_archive_borne_la_fenetre_et_reste_causal(tmp_path):
    now = 1_794_000_000_000
    state = {BOT: F.LeaderWatermark(), SLOW: F.LeaderWatermark()}
    appels: list[tuple[str, int]] = []

    def poster(vault, start_ms, end_ms):
        appels.append((vault, start_ms))
        return []

    P.poll_once(tmp_path, [BOT, SLOW], state, poster=poster, now_ms=now, echantillon_ms={BOT: 120_000})
    assert dict(appels) == {BOT: now - 120_000, SLOW: now - P.BOOTSTRAP_LOOKBACK_MS}
    # relevé suivant, 30 min plus tard : le robot n'est relu que sur ses 2 dernières minutes,
    # en 2 pages au plus, alors que le leader lent garde la pagination complète (aucun fill perdu).
    state = {BOT: F.LeaderWatermark(high_water_ms=now, initialised=True),
             SLOW: F.LeaderWatermark(high_water_ms=now, initialised=True)}
    later = now + 1_800_000
    pages: dict[str, int] = {}

    def poster_plein(vault, start_ms, end_ms):
        pages[vault] = pages.get(vault, 0) + 1
        debut = max(start_ms, later - 100_000) + pages[vault] * 10
        return [{"time": debut + i, "tid": pages[vault] * 10_000 + i, "coin": "BTC", "px": "1", "sz": "1",
                 "side": "B", "hash": "0x1", "oid": i} for i in range(F.RESPONSE_PAGE_CAP)]

    emis = P.poll_once(tmp_path, [BOT, SLOW], state, poster=poster_plein, now_ms=later,
                       echantillon_ms={BOT: 120_000})
    assert pages == {BOT: 2, SLOW: 8}
    lignes = [json.loads(x) for x in (tmp_path / P.OUT_FILLS).read_text(encoding="utf-8").splitlines()]
    assert emis == len(lignes) > 0
    for ligne in lignes:  # tout fill émis a été observé dans sa fenêtre de fraîcheur
        assert 0 <= ligne["observed_at_ms"] - ligne["time"] <= F.DEFAULT_MAX_OBSERVATION_LAG_MS


def test_premier_releve_des_leaders_d_archive_etale_les_autres_immediats():
    leaders = [SLOW, BOT, CLONE, NEW]
    plan = {SLOW: "PRIORITAIRE", BOT: "ARCHIVE", CLONE: "ARCHIVE"}
    due = F.staggered_first_due_ms(leaders, plan, 1_000.0)
    assert due[SLOW] == due[NEW] == 1_000.0                       # utiles et non classés : tout de suite
    assert due[BOT] == 1_000.0 and due[CLONE] == 1_000.0 + F.ARCHIVE_INTERVAL_S * 500.0   # étalés sur 30 min
    assert F.staggered_first_due_ms(leaders, {}, 5.0) == {v: 5.0 for v in leaders}   # sans plan : inchangé


def test_les_archives_ne_sont_suivies_que_la_ou_le_plan_du_labo_existe(tmp_path, monkeypatch):
    """Une lane cloud n'a pas le plan : elle ne doit jamais interroger les robots à pleine cadence."""
    import argparse

    monkeypatch.delenv("ALINA_POLL_CADENCE_LABO", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "copy_vault_leaders.json").write_text(json.dumps(
        {"vaults": [SLOW, NEW], "vaults_archive": [BOT, CLONE, NEW, "pas-une-adresse", 7]}), encoding="utf-8")
    args = argparse.Namespace(leaders="", leaders_file="config/copy_vault_leaders.json")
    suivis = P._lire_leaders(args, tmp_path)
    assert suivis == [SLOW, NEW]                                    # ``vaults`` seule : ce que lit une lane
    archives = P._lire_archives(args, tmp_path)
    assert archives == [BOT, CLONE, NEW]
    assert P.archives_a_suivre(tmp_path, suivis, archives) == []    # cloud : pas de plan -> aucune archive
    besoins = tmp_path / P.BESOINS_COLLECTE
    besoins.parent.mkdir(parents=True)
    besoins.write_text(json.dumps(NEEDS), encoding="utf-8")
    assert P.archives_a_suivre(tmp_path, suivis, archives) == [BOT, CLONE]   # NEW n'est pas classé ARCHIVE
    monkeypatch.setenv("ALINA_POLL_CADENCE_LABO", "0")
    assert P.archives_a_suivre(tmp_path, suivis, archives) == []    # plan coupé : jamais à pleine cadence
    monkeypatch.delenv("ALINA_POLL_CADENCE_LABO")
    # liste donnée à la main, ou sources par défaut sans clé d'archive : rien d'ajouté
    assert P._lire_archives(argparse.Namespace(leaders=SLOW, leaders_file=""), tmp_path) == []
    assert P._lire_archives(argparse.Namespace(leaders="", leaders_file=""), tmp_path) == [BOT, CLONE, NEW]
