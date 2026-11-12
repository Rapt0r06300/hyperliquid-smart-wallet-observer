"""S1.6 / GIS1-GIS5 — « qui mène, et de combien de millisecondes », avec refus de conclure.

La recherche du 12/11 mesure que Binance précède Hyperliquid d'environ 700 ms (29/29 actifs), par
l'estimateur de Hayashi-Yoshida — le seul adapté à des séries échangées à des instants irréguliers et
non synchronisés. Elle avertit dans la même phrase qu'un « lead de 700 ms » est TRIVIAL à fabriquer par
dérive d'horloge, donnée périmée ou mauvais alignement de barres.

Ces tests verrouillent donc les deux moitiés du travail :

1. on retrouve bien un décalage CONNU, et dans le BON SENS (une erreur de signe inverserait la
   conclusion : « Hyperliquid mène Binance » — la pire erreur possible ici) ;
2. on REFUSE de conclure sur des séries indépendantes, sur une horloge qui dérive, sur un pic au bord
   du balayage, ou sur trop peu d'observations.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import price_discovery as PD  # noqa: E402

T0 = 1_800_000_000_000


def _marche(n: int = 400, pas_ms: int = 250, graine: int = 7,
            depart: int = T0) -> list[tuple[int, float]]:
    """Une marche aléatoire horodatée, cadence régulière."""
    rng = random.Random(graine)
    prix, ticks = 100.0, []
    for i in range(n):
        prix *= math.exp(rng.gauss(0.0, 0.001))
        ticks.append((depart + i * pas_ms, prix))
    return ticks


def _retarde(ticks: list[tuple[int, float]], retard_ms: int) -> list[tuple[int, float]]:
    """La MEME information, observée `retard_ms` plus tard : le suiveur parfait."""
    return [(ts + retard_ms, prix) for ts, prix in ticks]


# ------------------------------------------------------------------ on retrouve un décalage connu

def test_on_retrouve_un_decalage_de_700_ms_dans_le_bon_sens():
    a = _marche()
    b = _retarde(a, 700)
    r = PD.decalage_optimal(a, b, nom_a="Binance", nom_b="Hyperliquid")
    assert r["verdict"] == PD.VERDICT_MESURE
    assert r["decalage_ms"] == 700
    assert r["qui_mene"] == "Binance"                 # LE sens qui compte
    assert r["correlation"] > 0.9


def test_echanger_les_roles_inverse_le_signe_et_le_meneur():
    """Contrôle de cohérence élémentaire : si A mène B de +700, alors B « mène » A de -700."""
    a = _marche()
    b = _retarde(a, 700)
    direct = PD.decalage_optimal(a, b, nom_a="Binance", nom_b="Hyperliquid")
    inverse = PD.decalage_optimal(b, a, nom_a="Hyperliquid", nom_b="Binance")
    assert inverse["decalage_ms"] == -direct["decalage_ms"]
    assert inverse["qui_mene"] == "Binance"           # le meneur ne depend pas de l'ordre des arguments


def test_une_serie_contre_elle_meme_ne_mene_pas(capsys):
    """Placebo : aucune avance ne doit apparaitre là où il n'y en a pas."""
    a = _marche()
    r = PD.decalage_optimal(a, list(a), nom_a="A", nom_b="A_bis")
    assert r["decalage_ms"] == 0
    assert r["qui_mene"] is None


def test_un_decalage_plus_fin_que_le_pas_est_arrondi_au_pas():
    a = _marche()
    b = _retarde(a, 300)
    r = PD.decalage_optimal(a, b, pas_ms=100, borne_ms=1000)
    assert r["decalage_ms"] == 300


# ------------------------------------------------------------------ refus de conclure

def test_deux_series_independantes_ne_donnent_PAS_de_meneur():
    """Le faux positif le plus courant : deux marches sans rapport produisent toujours un argmax.
    Il faut refuser, pas publier un lead inventé."""
    a = _marche(graine=1)
    b = _marche(graine=99)
    r = PD.decalage_optimal(a, b, nom_a="A", nom_b="B")
    assert r["verdict"] == PD.VERDICT_PIC_NON_DISTINCT
    assert r["qui_mene"] is None
    assert "courbe plate" in r["raison"]
    # le critere est RELATIF a la dispersion : calibre le 12/11, le bruit reste sous 3 ecarts-MAD
    assert r["ecarts_de_dispersion"] < PD.FACTEUR_DISPERSION_MINIMAL


def test_une_horloge_qui_DERIVE_est_detectee_et_non_publiee():
    """LE garde-fou dont la source parle : une horloge qui dérive fabrique un lead de toutes pièces.
    Ici le retard passe de 100 ms (1re moitié) à 1500 ms (2e moitié) : ce n'est pas une précédence
    de marché, et l'outil doit le dire au lieu de conclure."""
    a = _marche(n=600)
    moitie = len(a) // 2
    b = _retarde(a[:moitie], 100) + _retarde(a[moitie:], 1500)
    r = PD.decalage_optimal(a, b, nom_a="Binance", nom_b="Hyperliquid")
    assert r["verdict"] == PD.VERDICT_ARTEFACT_HORLOGE
    assert r["qui_mene"] is None
    assert "derive d'horloge" in r["raison"]
    assert "derive_ms" in r


def test_un_plateau_qui_touche_le_bord_du_balayage_est_signale():
    """Vrai decalage de 300 ms mais fenetre de +-200 : le plateau du pic touche le bord, donc le vrai
    decalage est DEHORS. Il faut elargir, pas publier la valeur tronquee."""
    a = _marche()
    b = _retarde(a, 300)
    r = PD.decalage_optimal(a, b, pas_ms=100, borne_ms=200)
    assert r["verdict"] == PD.VERDICT_BORD_DU_BALAYAGE
    assert r["plateau_ms"][-1] >= 200
    assert "probablement DEHORS" in r["raison"]


def test_un_decalage_trop_loin_pour_laisser_le_moindre_chevauchement_est_juste_illisible():
    """Nuance honnete : a 2000 ms de decalage avec des ticks de 250 ms, AUCUN intervalle ne se
    chevauche dans une fenetre de +-500. Il n'y a alors rien a voir du tout — ce n'est pas « un pic au
    bord », c'est une courbe plate. L'outil doit dire l'un ou l'autre, jamais inventer une valeur."""
    a = _marche()
    b = _retarde(a, 2000)
    r = PD.decalage_optimal(a, b, pas_ms=100, borne_ms=500)
    assert r["verdict"] == PD.VERDICT_PIC_NON_DISTINCT
    assert r["qui_mene"] is None


def test_le_decalage_rendu_est_le_CENTRE_du_plateau_pas_son_premier_point():
    """La correlation HY ne resout pas plus fin que l'intervalle entre ticks : autour du vrai decalage,
    une PLAGE est quasi equivalente. Prendre l'argmax brut choisissait le premier point du plateau et
    sous-estimait (mesure du 12/11 : 100 ms annonces pour un vrai 300 ms). Le centre retrouve la vraie
    valeur."""
    a = _marche()
    r = PD.decalage_optimal(a, _retarde(a, 700), nom_a="Binance", nom_b="HL")
    debut, fin = r["plateau_ms"]
    assert debut < r["decalage_ms"] < fin               # il y a bien un plateau, et on est dedans
    assert r["decalage_ms"] == 700                      # et c'est la vraie valeur

    plat = PD.decalage_optimal(a, list(a))
    assert plat["decalage_ms"] == 0                     # idem pour l'absence de decalage


def test_trop_peu_d_observations_ne_conclut_pas():
    a = _marche(n=5)
    b = _retarde(a, 700)
    r = PD.decalage_optimal(a, b)
    assert r["verdict"] == PD.VERDICT_SIGNAL_INSUFFISANT
    assert r["decalage_ms"] is None and r["qui_mene"] is None
    assert str(PD.MIN_RENDEMENTS) in r["raison"]


def test_deux_series_sans_aucun_chevauchement_ne_concluent_pas():
    a = _marche(n=100, depart=T0)
    b = _marche(n=100, depart=T0 + 10_000_000)          # trois heures plus tard
    r = PD.decalage_optimal(a, b)
    assert r["verdict"] in {PD.VERDICT_SIGNAL_INSUFFISANT, PD.VERDICT_PIC_NON_DISTINCT}
    assert r["qui_mene"] is None


# ------------------------------------------------------------------ robustesse des entrées

def test_les_prix_absurdes_et_les_horloges_qui_reculent_sont_ecartes():
    ticks = [(T0, 100.0), (T0 + 100, 0.0), (T0 + 200, 101.0), (T0 + 150, 102.0),
             (T0 + 300, -5.0), (T0 + 400, 103.0), ("pas-un-ts", 104.0), (T0 + 500,)]
    rends = PD.rendements_horodates(ticks)
    # retenus : 100 @T0, 101 @+200, 103 @+400  => 2 rendements
    assert len(rends) == 2
    assert all(debut < fin for debut, fin, _r in rends)


def test_hayashi_yoshida_refuse_le_vide_et_la_variance_nulle():
    assert PD.hayashi_yoshida([], []) == (None, 0)
    plat = [(T0, T0 + 100, 0.0), (T0 + 100, T0 + 200, 0.0)]
    assert PD.hayashi_yoshida(plat, plat) == (None, 0)


def test_la_serie_asynchrone_est_geree_sans_reechantillonnage():
    """Le point même de Hayashi-Yoshida : des cadences DIFFERENTES ne doivent pas casser la mesure
    (une grille commune aurait fabrique du biais)."""
    a = _marche(n=400, pas_ms=250, graine=3)
    b = [(ts + 700, prix) for ts, prix in _marche(n=400, pas_ms=250, graine=3)][::3]   # 3x moins dense
    r = PD.decalage_optimal(a, b, nom_a="Binance", nom_b="Hyperliquid")
    assert r["verdict"] == PD.VERDICT_MESURE
    assert r["qui_mene"] == "Binance"
    assert 400 <= r["decalage_ms"] <= 1000            # retrouvé malgré l'asynchronie


# ------------------------------------------------------------------ non-régression de la couche d'origine

def test_la_couche_crosscorr_d_origine_est_intacte():
    a = [0.01, -0.02, 0.03, -0.01, 0.02, 0.0, -0.03, 0.01]
    r = PD.crosscorr_lead(a, a, max_lag=2)
    assert r["peak_lag"] == 0
    scores = PD.venue_leader_score({"X": a, "Y": a}, max_lag=2)
    assert set(scores) == {"X", "Y"}
