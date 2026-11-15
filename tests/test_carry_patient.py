"""La seule politique dont les preuves disent qu'elle a une esperance positive.

Mesure publiee sur deux ans : la regle a SEUIL produit le PLUS de revenu brut de toutes les regles
testees et finit a -9 % a -15 % net (l'execution consomme 3x le brut) ; la regle patiente, sur une
HORLOGE de 30 jours (1 a 5 allers-retours en DEUX ANS), rend +2,7 % a +5,4 % net.

Ces tests verrouillent les quatre regles non negociables : horloge et pas seuil, aucune selection,
CAUSALITE STRICTE, portes de survie d'abord. Le test de causalite est le plus important du
fichier : sans lui, toute mesure de cette politique serait un lookahead deguise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import carry_patient as C  # noqa: E402


# ------------------------------------------------------------------ CAUSALITE

def test_le_classement_EXCLUT_l_heure_de_decision():
    """LE test qui compte. Inclure l'heure de decision ferait entrer dans le classement une
    information qu'on n'avait pas au moment de decider : la frontiere exacte entre une mesure et
    un lookahead."""
    serie = {10: 1.0, 11: 1.0, 12: 999.0}     # 12 = l'heure de decision, valeur aberrante
    moyenne = C.moyenne_anterieure(serie, fin_exclue=12, fenetre_h=5)
    assert moyenne == pytest.approx(1.0)      # la valeur de l'heure 12 ne doit PAS entrer


def test_une_fenetre_sans_donnee_rend_None_et_pas_zero():
    """Zero serait un classement : « funding nul ». None est l'absence de classement."""
    assert C.moyenne_anterieure({50: 1.0}, fin_exclue=10, fenetre_h=5) is None


# ------------------------------------------------------------------ CONVENTION DE SIGNE

def test_un_SHORT_encaisse_le_funding_POSITIF():
    """Sur Hyperliquid, un funding positif = les longs paient les shorts."""
    serie = {0: 0.001, 1: 0.001, 2: 0.001}
    total, heures = C.carry_encaisse(serie, debut=0, fin_exclue=3, sens=C.SHORT)
    assert total == pytest.approx(0.003)
    assert heures == 3


def test_un_LONG_encaisse_le_funding_NEGATIF():
    serie = {0: -0.001, 1: -0.001}
    total, _ = C.carry_encaisse(serie, debut=0, fin_exclue=2, sens=C.LONG)
    assert total == pytest.approx(0.002)


def test_les_heures_manquantes_sont_COMPTEES_separement():
    """Une periode a trous ne doit pas etre presentee comme une periode pleine."""
    total, heures = C.carry_encaisse({0: 0.001, 5: 0.001}, debut=0, fin_exclue=10,
                                     sens=C.SHORT)
    assert heures == 2 and total == pytest.approx(0.002)


# ------------------------------------------------------------------ UNE REVISION

def _univers(n=12, base=0.0001):
    """n coins de funding croissant, constant dans le temps."""
    return {f"C{i}": {h: base * (i + 1) for h in range(0, 400)} for i in range(n)}


def test_on_shorte_le_HAUT_du_classement_et_on_longe_le_BAS():
    r = C.une_revision(_univers(), instant=200, duree_h=100, fenetre_h=168, k=3)
    assert r["verdict"] == C.MESURE
    assert r["shorts"] == ["C11", "C10", "C9"]      # funding le plus haut
    assert set(r["longs"]) == {"C0", "C1", "C2"}    # le plus bas
    # les deux jambes encaissent : shorts sur funding positif, longs sur le moins positif
    assert r["rendement_brut"] > 0


def test_pas_assez_de_coins_REFUSE_au_lieu_de_reduire_le_portefeuille_en_silence():
    """Construire un portefeuille plus petit changerait la strategie sans le dire."""
    r = C.une_revision(_univers(n=4), instant=200, duree_h=100, fenetre_h=168, k=5)
    assert r["verdict"] == C.NON_MESURABLE
    assert r["motif"] == C.PAS_ASSEZ_DE_COINS
    assert r["requis"] == 10


# ------------------------------------------------------------------ L'HORLOGE

def test_le_cout_est_preleve_UNE_FOIS_PAR_REVISION():
    """Tout l'interet de l'horloge : une regle a seuil paierait ce cout des dizaines de fois sur
    la meme periode. C'est ce qui fait la difference entre -9 % et +2,7 %."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 2000)} for i in range(12)}
    sans = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5)
    avec = C.mesurer(univers, cout_aller_retour=0.01, horloge_h=720, fenetre_h=168, k=5)
    assert sans["verdict"] == avec["verdict"] == C.MESURE
    assert sans["revisions"] == avec["revisions"]
    ecart = sans["net_moyen"] - avec["net_moyen"]
    assert ecart == pytest.approx(0.01)        # exactement UN cout, pas un par heure


def test_une_histoire_trop_courte_pour_UNE_revision_est_refusee():
    univers = {f"C{i}": {h: 0.0001 for h in range(0, 100)} for i in range(12)}
    r = C.mesurer(univers, cout_aller_retour=0.001, horloge_h=720, fenetre_h=168, k=5)
    assert r["verdict"] == C.NON_MESURABLE
    assert r["motif"] == C.AUCUNE_REVISION
    assert "une seule revision" in r["lecture"]


# ------------------------------------------------------------------ AUCUNE SELECTION

def test_le_balayage_publie_TOUS_les_k_et_n_en_elit_aucun():
    """Lire le meilleur k et le presenter comme le resultat reproduirait exactement le PBO 0,81."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 2000)} for i in range(20)}
    b = C.balayage_sans_selection(univers, cout_aller_retour=0.001, ks=[2, 3, 5, 8])
    assert set(b["par_k"]) == {2, 3, 5, 8}
    assert b["convention"] == C.K_PAR_JAMBE       # la convention est fixee d'avance
    assert "PBO" in b["avertissement"]
    # aucune cle ne designe un gagnant
    assert not any("meilleur" in c or "optimal" in c for c in b)


# ------------------------------------------------------------------ LA JAMBE PRIX

def test_un_prix_MANQUANT_rend_None_et_jamais_zero():
    """LE refus qui compte sur la jambe prix. Zero affirmerait « le prix n'a pas bouge » ; un prix
    manquant est une ABSENCE de mesure. Les confondre transformerait un trou de donnees en bonne
    nouvelle — la faute exacte que `markout` refuse deja pour les mids."""
    assert C.pnl_de_prix({}, debut=0, fin_exclue=10, sens=C.LONG) is None
    assert C.pnl_de_prix({0: 100.0}, debut=0, fin_exclue=10, sens=C.LONG) is None  # sortie absente
    assert C.pnl_de_prix({9: 100.0}, debut=0, fin_exclue=10, sens=C.LONG) is None  # entree absente


def test_le_signe_du_pnl_de_prix_suit_le_sens():
    hausse = {0: 100.0, 9: 110.0}
    assert C.pnl_de_prix(hausse, debut=0, fin_exclue=10, sens=C.LONG) == pytest.approx(0.10)
    assert C.pnl_de_prix(hausse, debut=0, fin_exclue=10, sens=C.SHORT) == pytest.approx(-0.10)


def test_le_prix_entre_dans_le_NET_et_peut_le_RETOURNER():
    """Mesurer le seul funding d'un livre long/short serait la meme faute que mesurer le seul
    demi-spread d'un remplissage passif. Un mouvement relatif defavorable doit pouvoir effacer
    le carry — et le resultat doit le MONTRER."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 2000)} for i in range(12)}
    # les coins les plus shortes (funding haut) montent fortement => le short perd
    prix = {f"C{i}": {h: 100.0 * (1.0 + 0.001 * h * (i + 1)) for h in range(0, 2000)}
            for i in range(12)}
    sans = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5)
    avec = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5,
                     prix=prix)
    assert sans["verdict"] == avec["verdict"] == C.MESURE
    assert sans["prix_pnl_moyen"] is None
    assert avec["prix_pnl_moyen"] is not None
    assert avec["net_moyen"] < sans["net_moyen"]      # le prix a bien pese
    assert "prix" in avec["lecture"]


def test_sans_prix_la_lecture_DIT_que_le_prix_n_est_pas_mesure():
    """Un resultat de funding seul ne doit pas pouvoir etre lu comme un resultat complet."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 2000)} for i in range(12)}
    r = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5)
    assert "prix NON MESURE" in r["lecture"]


def test_aucune_jambe_chiffrable_en_prix_ne_devient_PAS_prix_neutre():
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 400)} for i in range(12)}
    r = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=5, prix={})
    assert r["verdict"] == C.MESURE
    assert r["prix_pnl"] is None
    assert r["motif_prix"] == C.PRIX_ABSENT
    assert r["total_brut"] == pytest.approx(r["rendement_brut"])


# ------------------------------------------------------------------ L'INVERSION CORRECTE

def test_inverser_retourne_les_POSITIONS_pas_le_signe_du_funding():
    """Nier les valeurs de funding fabriquerait un revenu fictif. Le signe du test : une strategie
    et son exact oppose doivent avoir des FUNDINGS OPPOSES, jamais le meme."""
    univers = _univers()
    normal = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3)
    inv = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3, inverser=True)
    # les positions sont echangees
    assert set(inv["shorts"]) == set(normal["longs"])
    assert set(inv["longs"]) == set(normal["shorts"])
    # et le funding encaisse est l'OPPOSE, pas l'identique
    assert inv["rendement_brut"] == pytest.approx(-normal["rendement_brut"])


def test_le_livre_inverse_PAIE_le_funding():
    """Longer le funding haut et shorter le bas fait payer sur les deux jambes : le pari devient
    purement un pari de prix. Un resultat qui montrerait un revenu de funding POSITIF dans ce
    sens serait un artefact de calcul."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 2000)} for i in range(12)}
    r = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5,
                  inverser=True)
    assert r["verdict"] == C.MESURE
    assert r["funding_moyen"] < 0


# ------------------------------------------------------------------ LE CHEVAUCHEMENT

def test_le_pas_donne_PLUS_de_detentions_sur_la_MEME_histoire():
    """A 211 j d'histoire et 30 j d'horloge, on n'a que 6 observations disjointes — et une seule
    periode defavorable pese alors un sixieme du verdict. C'est exactement ce qui s'est produit :
    une revision a -22,8 % ecrasait les cinq autres."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 3000)} for i in range(12)}
    disjoint = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5)
    chevauche = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5,
                          pas_h=168)
    assert chevauche["revisions"] > disjoint["revisions"] * 3


def test_le_chevauchement_est_DECLARE_non_independant():
    """Des fenetres qui partagent 29 jours sur 30 ne sont pas des tirages distincts : on ne peut
    pas en tirer un t de Student. Le resultat doit le DIRE."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 3000)} for i in range(12)}
    r = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5, pas_h=168)
    assert r["fenetres_independantes"] is False
    assert "non independantes" in r["lecture"]
    disjoint = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5)
    assert disjoint["fenetres_independantes"] is True


def test_un_annualise_de_chevauchement_ne_SOMME_pas_les_periodes_recouvertes():
    """Additionner des detentions qui se recouvrent compterait le meme gain plusieurs fois et
    gonflerait l'annualise d'un facteur egal au recouvrement."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 3000)} for i in range(12)}
    disjoint = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5)
    chevauche = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5,
                          pas_h=168)
    # funding constant => le rendement par detention est le meme ; l'annualise doit donc etre
    # comparable, et surtout PAS multiplie par le nombre de fenetres en plus.
    assert chevauche["annualise"] == pytest.approx(disjoint["annualise"], rel=0.05)


# ------------------------------------------------------------------ SIGNAL SEPARE DU FUNDING

def test_le_signal_de_classement_est_SEPARABLE_du_funding_encaisse():
    """Sans cette separation, on ne peut pas repondre a « le funding n'est-il qu'un PROXY du
    momentum ? » : classer sur le funding force a le PAYER, alors que classer sur le momentum
    garde le gain de prix SANS le cout de funding."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 400)} for i in range(12)}
    # un signal qui classe dans l'ORDRE INVERSE du funding
    sig = {f"C{i}": {h: -0.0001 * (i + 1) for h in range(0, 400)} for i in range(12)}
    sans = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3)
    avec = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3, signal=sig)
    assert set(avec["shorts"]) == set(sans["longs"])      # le classement a bien change
    # mais le funding encaisse reste celui du VRAI funding, pas celui du signal
    assert avec["rendement_brut"] == pytest.approx(-sans["rendement_brut"])


def test_un_coin_sans_funding_n_est_PAS_ouvert_meme_s_il_a_un_signal():
    """On n'ouvre pas une jambe dont on ne saurait pas compter le cout de portage."""
    univers = {f"C{i}": {h: 0.0001 for h in range(0, 400)} for i in range(6)}
    sig = dict({f"C{i}": {h: float(i) for h in range(0, 400)} for i in range(6)},
               **{"INCONNU": {h: 999.0 for h in range(0, 400)}})
    r = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=2, signal=sig)
    assert "INCONNU" not in r["shorts"] and "INCONNU" not in r["longs"]


# ------------------------------------------------------------------ PONDERATION

def test_les_poids_sont_RENORMALISES_a_somme_un():
    """Sinon on comparerait deux livres de TAILLES differentes, et le gain serait un artefact
    d'echelle plutot qu'un effet de ponderation."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 400)} for i in range(12)}
    poids = {f"C{i}": float(i + 1) for i in range(12)}
    r = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3, poids=poids)
    total = sum(j["poids"] for j in r["jambes"] if j["heures"] > 0)
    assert total == pytest.approx(1.0)


def test_des_poids_tous_nuls_retombent_sur_l_equiponderation():
    """Un poids absent ou nul partout ne doit pas annuler le livre en silence."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 400)} for i in range(12)}
    r = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3,
                       poids={f"C{i}": 0.0 for i in range(12)})
    assert r["verdict"] == C.MESURE
    total = sum(j["poids"] for j in r["jambes"] if j["heures"] > 0)
    assert total == pytest.approx(1.0)


# ------------------------------------------------------------------ COMPOSITION

def test_la_composition_depasse_l_annualisation_simple():
    """91 rotations a +0,474 % composees font +53,9 %, pas +43,2 %. Ignorer la composition
    sous-estime d'environ un quart un livre qui tourne tous les 4 jours."""
    assert C._compose(0.00474, 96) == pytest.approx(0.539, abs=0.01)
    simple = 0.00474 / 96 * 8760
    assert C._compose(0.00474, 96) > simple


def test_un_capital_DETRUIT_ne_se_compose_pas():
    """Un net <= -100 % n'a pas de taux compose : c'est la ruine, pas un rendement."""
    assert C._compose(-1.0, 96) is None
    assert C._compose(-1.5, 96) is None


def test_les_deux_annualises_sont_PUBLIES():
    """La version simple reste la bonne pour comparer des horizons entre eux ; la composee est la
    bonne pour dire ce que le capital devient. On ne choisit pas a la place du lecteur."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 2000)} for i in range(12)}
    r = C.mesurer(univers, cout_aller_retour=0.0, horloge_h=720, fenetre_h=168, k=5)
    assert r["annualise"] is not None
    assert r["annualise_compose"] is not None


# ------------------------------------------------------------------ L'INDEX GLISSANT

def test_l_index_donne_EXACTEMENT_le_meme_resultat_que_le_calcul_direct():
    """LE test qui compte : une optimisation qui change le resultat n'est pas une optimisation,
    c'est un bug. On compare sur des series A TROUS, aux bords de fenetre."""
    import random
    rnd = random.Random(7)
    serie = {h: rnd.uniform(-0.001, 0.001) for h in range(0, 500) if rnd.random() > 0.3}
    idx = C.index_glissant(serie)
    for fin in (0, 1, 50, 96, 97, 200, 499, 500, 600):
        for fen in (1, 24, 96, 168, 1000):
            direct = C.moyenne_anterieure(serie, fin_exclue=fin, fenetre_h=fen)
            indexe = C.moyenne_indexee(idx, fin_exclue=fin, fenetre_h=fen)
            if direct is None:
                assert indexe is None, (fin, fen)
            else:
                assert indexe == pytest.approx(direct, rel=1e-12), (fin, fen)


def test_l_index_EXCLUT_la_borne_haute_comme_le_calcul_direct():
    """La causalite ne doit pas se perdre dans l'optimisation : `bisect_left` et non `bisect_right`
    sur la borne haute, sinon l'heure de decision entrerait dans le classement."""
    serie = {10: 1.0, 11: 1.0, 12: 999.0}
    idx = C.index_glissant(serie)
    assert C.moyenne_indexee(idx, fin_exclue=12, fenetre_h=5) == pytest.approx(1.0)


def test_l_index_PRESERVE_les_trous():
    """On cumule la somme ET le compte : la moyenne porte sur les heures REELLEMENT presentes.
    Sans le compte, une serie a trous serait divisee par trop et diluee vers zero."""
    serie = {0: 1.0, 5: 1.0}            # 2 points sur une fenetre de 10 heures
    idx = C.index_glissant(serie)
    assert C.moyenne_indexee(idx, fin_exclue=10, fenetre_h=10) == pytest.approx(1.0)


def test_une_revision_AVEC_index_donne_le_meme_livre_que_SANS():
    """L'index ne doit changer que la vitesse."""
    univers = {f"C{i}": {h: 0.0001 * (i + 1) for h in range(0, 400)} for i in range(12)}
    idx = {c: C.index_glissant(s) for c, s in univers.items()}
    sans = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3)
    avec = C.une_revision(univers, instant=200, duree_h=100, fenetre_h=168, k=3, index=idx)
    assert sans["shorts"] == avec["shorts"]
    assert sans["longs"] == avec["longs"]
    assert sans["rendement_brut"] == pytest.approx(avec["rendement_brut"])


def test_une_serie_vide_indexee_rend_None():
    assert C.moyenne_indexee(C.index_glissant({}), fin_exclue=10, fenetre_h=5) is None
