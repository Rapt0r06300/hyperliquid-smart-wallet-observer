"""Découverte des leaders guidée par le plan du labo : largeur plutôt que robots HFT."""
from __future__ import annotations

import json

import tools.fusionner_leaders_actifs as F


def _a(i: int) -> str:
    return "0x" + f"{i:040x}"


def test_sans_plan_le_comportement_historique_est_identique():
    cures, actifs = [_a(1), _a(2)], [_a(2), _a(3), _a(4)]
    assert F.construire_suivis(cures, actifs, cap=10) == [_a(1), _a(2), _a(3), _a(4)]
    assert F.construire_suivis(cures, actifs, cap=3) == [_a(1), _a(2), _a(3)]
    assert F.construire_suivis(cures, actifs, cap=10, plan={}) == [_a(1), _a(2), _a(3), _a(4)]


def test_ordre_exploration_stratifie_deterministe_et_couvre_tout_au_fil_des_jours():
    candidats = [_a(i) for i in range(100, 140)]            # classés par activité décroissante
    jour0 = F.ordre_exploration(candidats, jour=0)
    assert sorted(jour0) == sorted(candidats) and jour0 == F.ordre_exploration(candidats, jour=0)
    # les 4 premiers viennent de 4 tranches d'activité différentes, pas tous de la tête
    assert [candidats.index(v) // 10 for v in jour0[:4]] == [0, 1, 2, 3]
    vus = set()
    for jour in range(10):
        vus.update(F.ordre_exploration(candidats, jour=jour)[:4])
    assert vus == set(candidats)                            # en 10 jours, tout candidat a eu sa place
    assert F.ordre_exploration([], jour=3) == [] and F.ordre_exploration([_a(1)], jour=5) == [_a(1)]


def test_plan_labo_les_robots_ne_prennent_plus_les_places_de_decouverte():
    cures = [_a(1)]
    robots = [_a(i) for i in range(10, 20)]                 # tête du classement d'activité
    autres = [_a(i) for i in range(20, 40)]
    lent, swing = _a(50), _a(51)
    plan = {lent: "PRIORITAIRE", swing: "STANDARD", **{r: "ARCHIVE" for r in robots}}
    suivis = F.construire_suivis(cures, robots + autres, cap=8, plan=plan, jour=0)
    principal, archives = suivis[:8], suivis[8:]
    assert principal[:3] == [_a(1), lent, swing]            # vettés, puis lents mesurés
    assert not set(principal) & set(robots)                 # aucune place de découverte pour un robot
    assert len(set(principal[3:]) & set(autres)) == 5
    assert archives == robots                               # conservés dans l'univers, hors plafond
    assert len(suivis) == len(set(suivis))


def test_fusionner_trace_le_plan_applique(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / F.LEADERS).write_text(json.dumps({"vaults": [_a(1)]}), encoding="utf-8")
    (tmp_path / F.CLASSEMENT).write_text(json.dumps({"actifs": [{"vault": _a(10)}, {"vault": _a(20)}]}), encoding="utf-8")
    (tmp_path / F.BESOINS).write_text(json.dumps({"experiment_id": "exp-9", "leaders": [
        {"unit": _a(10), "addresses": [_a(10), _a(11)], "cadence": "ARCHIVE"},
        {"unit": _a(50), "addresses": [_a(50)], "cadence": "PRIORITAIRE"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(F.time, "time", lambda: 86_400.0 * 7)
    rapport = F.fusionner(tmp_path, cap=120)
    ecrit = json.loads((tmp_path / F.LEADERS).read_text(encoding="utf-8"))
    assert rapport["statut"] == "OK"
    # les archives ne sont PAS dans ``vaults`` (lue par les lanes cloud, qui n'ont pas le plan)
    assert ecrit["vaults"] == [_a(1), _a(50), _a(20)]
    assert ecrit["vaults_archive"] == [_a(10), _a(11)]
    assert rapport["archives"] == 2 and rapport["total"] == 5 and ecrit["n_actifs_ajoutes"] == 2
    assert ecrit["plan_labo"] == {"applique": True, "experiment_id": "exp-9", "jour_rotation": 7,
                                 "n_lents": 1, "n_archive": 2, "n_exploration": 1}
    # plan illisible : aucune erreur, retour au comportement historique
    (tmp_path / F.BESOINS).write_text("{", encoding="utf-8")
    F.fusionner(tmp_path, cap=120)
    assert json.loads((tmp_path / F.LEADERS).read_text(encoding="utf-8"))["plan_labo"]["applique"] is False


def test_des_places_restent_reservees_a_la_decouverte_meme_si_le_labo_connait_beaucoup_de_lents():
    """Constat réel : 0 place d'exploration quand les leaders classés saturaient le plafond."""
    cures = [_a(i) for i in range(1, 11)]                          # 10 vettés
    lents = {_a(i): "PRIORITAIRE" for i in range(100, 200)}        # 100 lents connus du labo
    nouveaux = [_a(i) for i in range(500, 560)]                    # jamais classés
    suivis = F.construire_suivis(cures, nouveaux, cap=50, plan=lents, jour=3)
    assert len(suivis) == 50 and suivis[:10] == cures
    explores = [v for v in suivis if v in set(nouveaux)]
    assert len(explores) == 10                                     # (50 - 10) // 4 places réservées
    assert len([v for v in suivis if v in lents]) == 30
    # peu de lents connus : la découverte prend toute la place restante (rien n'est gaspillé)
    peu = F.construire_suivis(cures, nouveaux, cap=50, plan={_a(100): "STANDARD"}, jour=3)
    assert len(peu) == 50 and len([v for v in peu if v in set(nouveaux)]) == 39


def test_un_leader_vette_reste_a_pleine_cadence_meme_classe_archive_et_sans_plan_rien_ne_change(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / F.LEADERS).write_text(json.dumps({"vaults": [_a(1), _a(2)]}), encoding="utf-8")
    (tmp_path / F.CLASSEMENT).write_text(json.dumps({"actifs": [{"vault": _a(30)}]}), encoding="utf-8")
    sans_plan = F.fusionner(tmp_path, cap=120)
    ecrit = json.loads((tmp_path / F.LEADERS).read_text(encoding="utf-8"))
    assert ecrit["vaults"] == [_a(1), _a(2), _a(30)] and ecrit["vaults_archive"] == []   # historique exact
    assert sans_plan["archives"] == 0
    (tmp_path / F.BESOINS).write_text(json.dumps({"experiment_id": "e", "leaders": [
        {"unit": _a(2), "addresses": [_a(2)], "cadence": "ARCHIVE"},      # vetté ET robot
        {"unit": _a(40), "addresses": [_a(40)], "cadence": "ARCHIVE"},
    ]}), encoding="utf-8")
    F.fusionner(tmp_path, cap=120)
    ecrit = json.loads((tmp_path / F.LEADERS).read_text(encoding="utf-8"))
    assert _a(2) in ecrit["vaults"] and ecrit["vaults_archive"] == [_a(40)]
    assert not set(ecrit["vaults"]) & set(ecrit["vaults_archive"])
