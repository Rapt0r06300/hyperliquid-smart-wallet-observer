"""L'ETA DE COLLECTE doit BOUGER avec le debit, et REFUSER plutot que rassurer.

CE QUE L'OPERATEUR A DEMANDE : << je veux voir un eta qui bouge et s'adapte au temps
restant selon le nombre de donnees collectees, pas comme une date fixe >>.

CE QUI BLOQUE REELLEMENT LE LABO, mesure le 22/11/2026 : non pas un volume d'octets, mais
le nombre de **journees UTC distinctes et DENSES** de signaux evaluables -- un signal dont
le carnet causal le precede de moins de 30 s, dans une journee portant au moins
`MIN_SIGNALS_PER_DAY` signaux. La porte exige `MINIMUM_SIGNAL_UTC_DAYS` journees.

D'OU VIENT L'ADAPTATION. Une journee UTC ne s'acquiert qu'une fois par jour calendaire, et
seulement si le debit la rend dense. Si le debit tombe, la journee en cours CESSE de
compter et l'ETA **recule** : c'est le comportement voulu, pas un defaut. Ces tests
verrouillent precisement ce recul -- sans eux, un ETA fige passerait pour correct.

ET TROIS REFUS, parce qu'un chiffre rassurant est pire que pas de chiffre :
debit nul -> `INFINI` ; debit non mesurable -> `INCONNU` ; jamais une duree inventee.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for dossier in ("tools", "src"):
    if str(RACINE / dossier) not in sys.path:
        sys.path.insert(0, str(RACINE / dossier))

import eta_donnees_labo as ETA  # noqa: E402

HEURE_S = 3600.0


def _cas(**ecarts):
    base = {
        "denses_acquis": 3, "requis": 6, "signaux_aujourdhui": 0,
        "seuil_par_jour": 10, "debit_par_heure": 600.0,
        "aujourdhui_deja_dense": False,
        "secondes_restantes_dans_la_journee": 10 * HEURE_S,
    }
    base.update(ecarts)
    return ETA.calculer_eta(**base)


# ------------------------------------------------------------------ les refus
def test_un_debit_NUL_rend_INFINI_jamais_une_duree():
    """La collecte eteinte ne doit pas produire un ETA : elle n'arrivera jamais."""
    verdict = _cas(debit_par_heure=0.0)
    assert verdict["statut"] == "INFINI"
    assert verdict["heures"] is None
    assert "eteinte" in verdict["motif"]


def test_un_debit_NON_MESURABLE_rend_INCONNU_et_pas_zero():
    """`None` veut dire << je n'ai pas su mesurer >>. Zero voudrait dire << rien n'arrive >>."""
    verdict = _cas(debit_par_heure=None)
    assert verdict["statut"] == "INCONNU"
    assert verdict["heures"] is None


def test_les_journees_DEJA_acquises_donnent_ATTEINT():
    verdict = _cas(denses_acquis=7, requis=6)
    assert verdict["statut"] == "ATTEINT"
    assert verdict["heures"] == 0.0
    assert verdict["manquantes"] == 0


# ------------------------------------------------------- l'ETA BOUGE avec le debit
def test_un_debit_PLUS_FAIBLE_allonge_l_ETA():
    """Le coeur de la demande : l'ETA suit le debit, il n'est pas une date fixe."""
    rapide = _cas(debit_par_heure=6_000.0, signaux_aujourdhui=0, seuil_par_jour=1_000)
    lent = _cas(debit_par_heure=600.0, signaux_aujourdhui=0, seuil_par_jour=1_000)
    assert rapide["heures"] < lent["heures"], (rapide, lent)


def test_un_debit_TROP_FAIBLE_fait_PERDRE_la_journee_en_cours_et_RECULER_l_ETA():
    """Si le seuil ne peut pas etre atteint avant minuit, la journee ne comptera pas :
    il faut une journee calendaire de PLUS. C'est le recul que l'operateur veut voir."""
    suffisant = _cas(debit_par_heure=1_000.0, seuil_par_jour=100,
                     secondes_restantes_dans_la_journee=10 * HEURE_S)
    insuffisant = _cas(debit_par_heure=1.0, seuil_par_jour=100_000,
                       secondes_restantes_dans_la_journee=HEURE_S)
    assert suffisant["statut"] == "EN_COURS"
    assert insuffisant["statut"] == "JOURNEE_EN_COURS_PERDUE"
    assert insuffisant["heures"] > suffisant["heures"]
    assert insuffisant["journees_calendaires_ensuite"] == insuffisant["manquantes"]


def test_des_signaux_DEJA_collectes_aujourdhui_raccourcissent_l_ETA():
    """<< s'adapte selon le nombre de donnees collectees >> : ce qui est deja acquis compte."""
    vide = _cas(signaux_aujourdhui=0, seuil_par_jour=1_000)
    avance = _cas(signaux_aujourdhui=900, seuil_par_jour=1_000)
    assert avance["heures"] < vide["heures"]


def test_une_journee_DEJA_dense_ne_se_refait_pas():
    deja = _cas(aujourdhui_deja_dense=True)
    assert deja["heures_pour_finir_aujourdhui"] == 0.0
    assert deja["journees_calendaires_ensuite"] == deja["manquantes"] - 1


def test_le_PLANCHER_calendaire_domine_quel_que_soit_le_debit():
    """Aucun debit ne fait apparaitre deux journees UTC le meme jour : 3 journees
    manquantes ne peuvent pas prendre moins de 2 journees calendaires."""
    verdict = _cas(denses_acquis=3, requis=6, debit_par_heure=10_000_000.0)
    assert verdict["heures"] >= 48.0, verdict


# ------------------------------------------------------- la densite, comme le labo
def test_une_journee_SOUS_le_seuil_ne_compte_pas_comme_dense():
    jour = ETA.JOUR_MS
    base = 10 * jour
    maigre = [base + i for i in range(3)]
    grasse = [base + jour + i for i in range(50)]
    bilan = ETA.jours_denses(maigre + grasse, seuil_par_jour=10)
    assert bilan["nombre_denses"] == 1, bilan
    assert bilan["denses"] == [base // jour + 1]


def test_un_horodatage_non_entier_ne_cree_pas_une_journee():
    bilan = ETA.jours_denses(["1700000000000", None, True, -5, 0], seuil_par_jour=1)
    assert bilan["nombre_denses"] == 0


# ------------------------------------------------------- l'affichage ne ment pas
def test_une_duree_INCONNUE_s_affiche_en_point_d_interrogation():
    assert ETA.duree_lisible(None) == "?"


def test_la_duree_lisible_est_juste():
    assert ETA.duree_lisible(0.5) == "30 min"
    assert ETA.duree_lisible(3.0) == "3 h 00 min"
    assert ETA.duree_lisible(49.5) == "2 j 01 h 30 min"


# ------------------------------------------------------- le debit refuse sans mentir
def test_un_ruban_ABSENT_rend_un_debit_INCONNU_et_le_nomme(tmp_path):
    mesure = ETA.MesureDeDebit(tmp_path / "jamais_ecrit.jsonl")
    lu = mesure.lire()
    assert lu["debit_par_heure"] is None
    assert lu["motif"] == "RUBAN_ILLISIBLE"


def test_la_PREMIERE_mesure_ne_pretend_pas_connaitre_le_debit(tmp_path, monkeypatch):
    """Une croissance se mesure entre DEUX instants : la premiere lecture ne sait rien."""
    ruban = tmp_path / "fills.jsonl"
    ruban.write_text("\n".join('{"ts_ms":1,"coin":"BTC"}' for _ in range(50)) + "\n",
                     encoding="utf-8")
    horloge = iter((0.0, 1.0))
    monkeypatch.setattr(ETA.time, "monotonic", lambda: next(horloge))
    mesure = ETA.MesureDeDebit(ruban)
    assert mesure.lire()["motif"] == "PREMIERE_MESURE"
    ruban.write_text(ruban.read_text(encoding="utf-8") + '{"ts_ms":2,"coin":"BTC"}\n', encoding="utf-8")
    assert mesure.lire()["debit_par_heure"] is not None   # la deuxieme, oui


def test_un_ruban_qui_GRANDIT_donne_un_debit_positif(tmp_path, monkeypatch):
    ruban = tmp_path / "fills.jsonl"
    ligne = '{"ts_ms":1700000000000,"coin":"BTC","px":1.0}\n'
    ruban.write_text(ligne * 100, encoding="utf-8")
    horloge = iter((0.0, 1.0))
    monkeypatch.setattr(ETA.time, "monotonic", lambda: next(horloge))
    mesure = ETA.MesureDeDebit(ruban)
    mesure.lire()                                  # amorce
    with ruban.open("a", encoding="utf-8") as fh:
        fh.write(ligne * 500)
    lu = mesure.lire()
    assert lu["debit_par_heure"] is not None
    assert lu["debit_par_heure"] > 0
    assert lu["lignes_par_minute"] > 0


def test_le_ruban_est_CHERCHE_a_plusieurs_endroits_et_on_dit_lesquels(tmp_path):
    """Un << ruban illisible >> doit nommer ce qu'il a cherche : sinon on croit a une
    collecte morte alors qu'on regardait au mauvais endroit (mesure du 22/11/2026)."""
    trouve, cherches = ETA.trouver_ruban(tmp_path)
    assert trouve is None
    assert len(cherches) >= 2
    cible = tmp_path / ETA.RUBANS_FILLS[1]
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text("{}\n", encoding="utf-8")
    trouve, _ = ETA.trouver_ruban(tmp_path)
    assert trouve == cible


def test_la_sonde_par_defaut_choisit_le_rapport_le_plus_recent(tmp_path):
    rapports = tmp_path / "runtime" / "reports"
    rapports.mkdir(parents=True)
    ancien = rapports / "sonde_horloges_20261122.json"
    recent = rapports / "sonde_horloges_20261123.json"
    ancien.write_text("{}", encoding="utf-8")
    recent.write_text("{}", encoding="utf-8")
    ancien.touch()
    recent.touch()
    os.utime(ancien, (1_000, 1_000))
    os.utime(recent, (2_000, 2_000))

    assert ETA.trouver_sonde(tmp_path) == recent


def test_l_eta_recharge_la_sonde_a_chaque_rafraichissement(tmp_path, monkeypatch, capsys):
    rapport = tmp_path / "runtime" / "reports" / "sonde_horloges_20261123.json"
    rapport.parent.mkdir(parents=True)

    def ecrire(jours: int) -> None:
        rapport.write_text(
            json.dumps({"appariement": {"jours_DENSES": jours}}), encoding="utf-8"
        )

    ecrire(0)

    def avancer_la_sonde(_secondes: float) -> None:
        ecrire(6)

    monkeypatch.setattr(ETA.time, "sleep", avancer_la_sonde)
    monkeypatch.setattr(ETA.os, "system", lambda _commande: 0)

    assert ETA.main(["--racine", str(tmp_path), "--tours", "2"]) == 0
    assert capsys.readouterr().out.count("[ATTEINT]") == 1


def _etude(racine, nom, verdicts):
    d = racine / ETA.ETUDES / nom
    d.mkdir(parents=True, exist_ok=True)
    (d / "resultat.json").write_text(json.dumps({"report": {"verdicts": verdicts}}), encoding="utf-8")


def test_les_besoins_viennent_des_etudes_du_labo_et_le_passage_le_plus_recent_fait_foi(tmp_path):
    """24/11/2026 : l'ETA affichait ATTEINT (7/6 journees) pendant que le labo repondait MORE_DATA (8 jours sur 20)."""
    _etude(tmp_path, "20261117T120000000000Z", [                               # même étude, plus ancienne
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "3 jour(s) hors echantillon < 20 requis", "required_independent_days": 20}])
    _etude(tmp_path, "20261124T113912441906Z-retro", [                         # AUTRE étude, même hypothèse
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "marche avant sur jours independants", "required_independent_days": 20}])
    _etude(tmp_path, "20261124T111022604526Z", [
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "8 jour(s) hors echantillon < 20 requis", "required_independent_days": 20},
        {"hypothesis": "copy_vault_fast_follow_taker_fills", "status": "REJECTED", "reason": "derive sous les frais"},
        {"hypothesis": "copy_vault_naive_mirror_taker", "status": "MORE_DATA", "reason": "l'IC 95 % contient zero"}])
    _etude(tmp_path, "20261123T013157066783Z-ouvertures", [
        {"hypothesis": "copy_vault_aggressive_open_drift", "status": "MORE_DATA",
         "reason": "16 jour(s), 25643 decision(s), 163 leader(s) ; il en faut au moins 30, 200 et 10"}])
    tous = ETA.besoins_du_labo(tmp_path)
    retro = [x for x in tous if x["etude"] == "retro"]
    assert len(retro) == 1 and retro[0]["restants"] is None                 # gardée à part, elle n'efface pas la base
    b = {x["hypothese"]: x for x in tous if x["etude"] != "retro"}
    assert (b["copy_vault_slow_inventory_replication"]["mesures"], b["copy_vault_slow_inventory_replication"]["requis"],
            b["copy_vault_slow_inventory_replication"]["restants"]) == (8, 20, 12)          # le 24/11, pas le 17/11
    assert b["copy_vault_slow_inventory_replication"]["date_estimee"].strftime("%d/%m") == "06/12"
    assert (b["copy_vault_aggressive_open_drift"]["mesures"], b["copy_vault_aggressive_open_drift"]["requis"]) == (16, 30)
    assert b["copy_vault_naive_mirror_taker"]["restants"] is None                          # jamais suppose
    texte = "\n".join(ETA.lignes_besoins(list(b.values())))
    assert "tranchee : REJECTED" in texte and "besoin non chiffre en jours" in texte


def test_une_echeance_deja_passee_demande_de_relancer_l_etude_et_n_est_pas_la_prochaine_date(tmp_path):
    """24/11/2026 : « prochaine hypothese tranchable vers le 17/11 » d'apres une etude du 12/11 jamais relancee."""
    from datetime import datetime, timezone

    _etude(tmp_path, "20261112T164759533677Z-ordres", [
        {"hypothesis": "copy_vault_leader_order_intent", "status": "MORE_DATA",
         "reason": "0 jour(s), 0 fill(s) ; il en faut au moins 5, 200 et 5"}])
    maintenant = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    b = ETA.besoins_du_labo(tmp_path)
    assert ETA.echeance_passee(b[0], maintenant)
    assert "PASSEE : relancer l'etude" in "\n".join(ETA.lignes_besoins(b, maintenant))


def test_l_ecran_ne_dit_plus_ATTEINT_quand_les_etudes_attendent_des_jours(tmp_path, monkeypatch, capsys):
    rapport = tmp_path / "runtime" / "reports" / "sonde_horloges_20261123.json"
    rapport.parent.mkdir(parents=True)
    rapport.write_text(json.dumps({"appariement": {"jours_DENSES": 7}}), encoding="utf-8")
    from datetime import datetime, timedelta, timezone

    maintenant = datetime.now(timezone.utc).replace(microsecond=0)          # indépendant du jour où tourne le test
    _etude(tmp_path, maintenant.strftime("%Y%m%dT%H%M%S") + "000000Z", [
        {"hypothesis": "copy_vault_slow_inventory_replication", "status": "MORE_DATA",
         "reason": "8 jour(s) hors echantillon < 20 requis", "required_independent_days": 20}])
    monkeypatch.setattr(ETA.os, "system", lambda _commande: 0)
    assert ETA.main(["--racine", str(tmp_path), "--une-fois"]) == 0
    sortie = capsys.readouterr().out
    attendu = (maintenant + timedelta(days=12)).strftime("%d/%m")
    assert f"ETA LABO (etudes)            : prochaine hypothese tranchable vers le {attendu}" in sortie
    assert "8 / 20  jours -> encore  12 j" in sortie
    assert "plancher du moteur" in sortie                     # le seuil de 6 journees reste dit, mais a sa place


def test_le_debit_se_mesure_d_abord_sur_le_ruban_du_poll():
    """24/11/2026 : le ruban WS ne bougeait presque pas (0,0 ligne/min) ; la collecte passe par le poll REST."""
    assert ETA.RUBANS_FILLS[0] == "runtime/data/vault_fills_poll.jsonl"
