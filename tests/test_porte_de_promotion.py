"""La porte de promotion — ce qui empeche le labo de devenir une machine a surapprendre.

« Si le labo trouve une meilleure strategie, le moteur doit s'en servir tout de suite. » Oui, mais
le labo SELECTIONNE : le meilleur de N candidats parait bon par pur HASARD, et c'est le mecanisme
du PBO de 0,81 mesure sur ce labo. Promouvoir le mieux mesure = promouvoir le plus chanceux.

Ces tests verrouillent les six refus. Chacun correspond a une erreur reellement commise le 14/11.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.strategies import porte_de_promotion as P  # noqa: E402


def _candidat(**kw):
    base = dict(strategy_id="carry_transversal_inverse", version=1,
                parametres=(("k", "3"), ("horizon_h", "96")), gel_instant_h=1000,
                annonce_par_periode=0.0047, essais=5)
    base.update(kw)
    return P.Candidat(**base)


def _resultat(**kw):
    base = dict(debut_instant_h=1000, observations_independantes=25,
                net_moyen_par_periode=0.0040, part_positive=0.68, t=4.2)
    base.update(kw)
    return P.ResultatHorsEchantillon(**base)


# --------------------------------------------------- le cas qui passe

def test_un_candidat_honnete_est_PROMU():
    r = P.juger(_candidat(), _resultat())
    assert r["verdict"] == P.PROMU
    assert "PROMU" in r["lecture"]


# --------------------------------------------------- les six refus

def test_essais_NON_DECLARES_est_un_refus_et_pas_un_essai_suppose():
    """Supposer `essais=1` reviendrait a promouvoir le plus chanceux. C'est le meme contrat que
    `test_transversal.tester(..., essais=)`."""
    r = P.juger(_candidat(essais=None), _resultat())
    assert r["verdict"] == P.REFUSE
    assert r["motif"] == P.MOTIF_ESSAIS_NON_DECLARES
    assert "plus chanceux" in r["lecture"]


def test_une_fenetre_ANTERIEURE_au_gel_est_refusee():
    """Un candidat ne se juge pas sur les donnees qui l'ont choisi."""
    r = P.juger(_candidat(gel_instant_h=1000), _resultat(debut_instant_h=900))
    assert r["verdict"] == P.REFUSE
    assert r["motif"] == P.MOTIF_FENETRE_CONTAMINEE


def test_pas_assez_d_observations_rend_PAS_ENCORE_et_non_REFUSE():
    """Distinction qui compte : « pas encore mesurable » n'est pas « refute ». Le 14/11, une
    detention a -22,8 % ecrasait les cinq autres sur six."""
    r = P.juger(_candidat(), _resultat(observations_independantes=6))
    assert r["verdict"] == P.PAS_ENCORE
    assert r["motif"] == P.MOTIF_PAS_ASSEZ_D_OBSERVATIONS


def test_un_net_hors_echantillon_NEGATIF_est_refuse():
    r = P.juger(_candidat(), _resultat(net_moyen_par_periode=-0.001))
    assert r["verdict"] == P.REFUSE
    assert r["motif"] == P.MOTIF_NEGATIF


def test_une_empreinte_MODIFIEE_est_refusee():
    """Un protocole reecrit apres coup ne prouve rien."""
    r = P.juger(_candidat(), _resultat(empreinte_candidat="0" * 32))
    assert r["verdict"] == P.REFUSE
    assert r["motif"] == P.MOTIF_EMPREINTE


def test_faire_BEAUCOUP_MIEUX_que_promis_est_AUSSI_un_refus():
    """Le refus le moins intuitif, et l'un des plus utiles : un candidat qui fait 5x mieux que
    promis n'est pas une bonne nouvelle, c'est une fuite ou une erreur de mesure."""
    r = P.juger(_candidat(annonce_par_periode=0.0047),
                _resultat(net_moyen_par_periode=0.0047 * 5))
    assert r["verdict"] == P.REFUSE
    assert r["motif"] == P.MOTIF_INCOHERENT
    assert "fuite ou une erreur de mesure" in r["lecture"]


# --------------------------------------------------- la correction de multiplicite

def test_plus_d_essais_exige_un_t_PLUS_HAUT():
    """Avec N essais, la chance seule produit un bon t dans ~N x alpha cas : Bonferroni divise le
    risque. C'est la correction STANDARD — un seuil invente se discute, un Bonferroni non."""
    seuils = [P._z_bonferroni(n) for n in (1, 9, 25, 450)]
    assert abs(seuils[0] - 1.96) < 0.01           # 1 essai = le z bilateral usuel a 5 %
    assert seuils == sorted(seuils)               # monotone
    assert abs(seuils[-1] - 3.86) < 0.02          # 450 essais -> 3,86


def test_le_meme_resultat_PASSE_a_1_essai_et_ECHOUE_a_100():
    """LE test qui montre a quoi sert la porte : un resultat identique est juge differemment
    selon le nombre de candidats essayes pour l'obtenir."""
    resultat = _resultat(t=2.5)
    assert P.juger(_candidat(essais=1), resultat)["verdict"] == P.PROMU      # seuil 1,96
    assert P.juger(_candidat(essais=100), resultat)["verdict"] == P.REFUSE   # seuil 3,48


# --------------------------------------------------- le t plutot que la frequence

def test_un_t_ABSENT_est_refuse_et_pas_suppose():
    """Sans dispersion, on ne distingue pas un edge d'une serie chanceuse."""
    r = P.juger(_candidat(), _resultat(t=None))
    assert r["verdict"] == P.REFUSE
    assert r["motif"] == P.MOTIF_T_ABSENT


def test_une_FAIBLE_part_positive_ne_ferme_PLUS_la_porte_si_le_t_tient():
    """LE correctif du 15/11. La premiere version jugeait sur la PART POSITIVE croissante avec les
    essais — un defaut, puisque l'edge de ce livre vient de l'ASYMETRIE (part positive 0,58) et non
    de la frequence. Un suiveur de tendance gagne 40 % du temps et fait fortune."""
    r = P.juger(_candidat(essais=9), _resultat(part_positive=0.40, t=3.5))
    assert r["verdict"] == P.PROMU
    assert "diagnostic" in r["lecture"]          # la part positive est publiee, pas exigee


def test_le_t_recompense_bien_l_ASYMETRIE():
    """Deux series de meme taille : l'une gagne souvent et petit, l'autre rarement et gros. Le t
    doit preferer celle qui gagne de l'argent, pas celle qui gagne souvent."""
    souvent_petit = [0.001] * 7 + [-0.004] * 3          # 70 % de reussite, moyenne negative
    rarement_gros = [-0.001] * 6 + [0.010] * 4          # 40 % de reussite, moyenne positive
    t_souvent = P.t_de_student(souvent_petit)
    t_gros = P.t_de_student(rarement_gros)
    assert t_souvent < 0 < t_gros


def test_le_t_refuse_une_serie_trop_courte_ou_sans_dispersion():
    assert P.t_de_student([0.01]) is None               # une seule observation
    assert P.t_de_student([0.01, 0.01, 0.01]) is None   # aucune dispersion


def test_l_empreinte_change_si_un_PARAMETRE_change():
    a = _candidat().empreinte()
    b = _candidat(parametres=(("k", "4"), ("horizon_h", "96"))).empreinte()
    assert a != b
    assert len(a) == 32


# --------------------------------------------------- la chaine labo -> porte -> moteur

def test_le_moteur_n_ouvre_RIEN_par_defaut(tmp_path):
    """Deny-by-default : dossier absent -> aucune strategie. Un systeme qui ouvre quand il ne sait
    pas est un systeme qui trade sur une erreur de lecture de fichier."""
    assert P.strategies_autorisees(tmp_path) == {}


def test_un_candidat_gele_se_relit_a_l_identique(tmp_path):
    c = _candidat()
    info = P.ecrire_proposition(tmp_path, c)
    relu = P.lire_proposition(info["chemin"])
    assert relu == c
    assert relu.empreinte() == info["empreinte"]


def test_un_candidat_RETOUCHE_a_la_main_est_REFUSE_a_la_relecture(tmp_path):
    """Tout l'interet de l'empreinte : maquiller le fichier le rend illisible, pas plus beau."""
    import json as _j
    c = _candidat()
    chemin = Path(P.ecrire_proposition(tmp_path, c)["chemin"])
    d = _j.loads(chemin.read_text(encoding="utf-8"))
    d["annonce_par_periode"] = 0.05        # on gonfle l'annonce sans toucher a l'empreinte
    chemin.write_text(_j.dumps(d), encoding="utf-8")
    assert P.lire_proposition(chemin) is None


def test_seul_un_PROMU_est_ecrit_et_devient_visible_du_moteur(tmp_path):
    c = _candidat()
    refus = P.juger(c, _resultat(net_moyen_par_periode=-0.01))
    assert P.enregistrer_promotion(tmp_path, c, refus) is None
    assert P.strategies_autorisees(tmp_path) == {}          # un refus n'ouvre rien
    promu = P.juger(c, _resultat())
    assert promu["verdict"] == P.PROMU
    assert P.enregistrer_promotion(tmp_path, c, promu) is not None
    vues = P.strategies_autorisees(tmp_path)
    assert c.strategy_id in vues
    assert vues[c.strategy_id]["essais"] == c.essais        # le moteur voit le nombre d'essais


def test_un_fichier_de_promotion_illisible_ne_fait_PAS_ouvrir(tmp_path):
    d = tmp_path / P.DOSSIER
    d.mkdir(parents=True, exist_ok=True)
    (d / "promue_casse.json").write_text("{ pas du json", encoding="utf-8")
    assert P.strategies_autorisees(tmp_path) == {}


def test_le_t_REFUSE_un_echantillon_minuscule():
    """15/11 — la version a 2 points rendait des `t` spectaculaires et vides : **4,25 sur TROIS
    observations** lors du test de la base, et son miroir a -4,74. Avec si peu de degres de
    liberte, un ecart-type minuscule fait exploser le `t`. **Un chiffre spectaculaire qu'on ne peut
    pas croire est plus dangereux qu'un refus.**"""
    assert P.t_de_student([0.01, 0.02, 0.015]) is None
    assert P.t_de_student([0.01] * (P.OBSERVATIONS_MINIMUM - 1)) is None
    bon = P.t_de_student([0.01, 0.02, 0.015, 0.012, 0.018, 0.011, 0.016, 0.013])
    assert bon is not None and bon > 0
