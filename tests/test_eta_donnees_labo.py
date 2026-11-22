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


def test_la_PREMIERE_mesure_ne_pretend_pas_connaitre_le_debit(tmp_path):
    """Une croissance se mesure entre DEUX instants : la premiere lecture ne sait rien."""
    ruban = tmp_path / "fills.jsonl"
    ruban.write_text("\n".join('{"ts_ms":1,"coin":"BTC"}' for _ in range(50)) + "\n",
                     encoding="utf-8")
    mesure = ETA.MesureDeDebit(ruban)
    assert mesure.lire()["motif"] == "PREMIERE_MESURE"
    assert mesure.lire()["debit_par_heure"] is not None   # la deuxieme, oui


def test_un_ruban_qui_GRANDIT_donne_un_debit_positif(tmp_path):
    ruban = tmp_path / "fills.jsonl"
    ligne = '{"ts_ms":1700000000000,"coin":"BTC","px":1.0}\n'
    ruban.write_text(ligne * 100, encoding="utf-8")
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
