"""LES FENETRES DE SIGNAL : lire les carnets que les signaux regardent, pas tout l'intervalle.

LA CONTRADICTION QUE CE CHEMIN LEVE, mesuree des deux cotes :

```
le split du labo exige >= 6 journees UTC distinctes DANS UNE SEULE tranche
la memoire               n'en tient qu'environ UNE a la fois
```

* 18/11/2026 (docstring de `load_observed_books`) : six jours denses de carnets = **~28 Go**,
  << un jour tient en memoire, les six ensemble non >> ;
* 22/11/2026 (mesure directe) : une tranche de **8 jours** a atteint **24,2 Go de RSS** et fait
  tomber la RAM libre a **0,6 Go (98 %)** ; la tranche de 16 jours a ete tuee par le systeme.

POURQUOI LE FILTRE NE PEUT RIEN CHANGER AUX APPARIEMENTS. Dans la fenetre de 8 jours, le coffre
porte **168 965 200 lignes de carnet** pour servir **~1,2 million d'appariements**. Or le labo
n'apparie un carnet que s'il PRECEDE le signal de moins de `MAX_TARGET_LAG_MS` (30 s) : toute
ligne hors de ces fenetres est lue, indexee, puis jamais consultee. Le filtre ne fait donc que
REJETER des lignes que personne ne regarde -- il ne peut pas ajouter de candidat, donc pas de
lookahead, et il ne peut pas en retirer un que le chargement complet aurait retenu.

CE QUE CES TESTS VERROUILLENT :
1. `None` par defaut -> comportement INCHANGE, bit pour bit (aucun appelant existant ne bouge) ;
2. EQUIVALENCE : pour un signal donne, les carnets retenus avec fenetres sont exactement ceux
   que le chargement complet aurait retenus dans la meme fenetre ;
3. la marge n'elargit que vers le PASSE : un carnet posterieur au signal reste exclu ;
4. une liste de fenetres VIDE est un REFUS, jamais zero carnet ;
5. les lignes ecartees sont COMPTEES, jamais oubliees en silence.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting.copy_vault_book_loader import (
    MARGE_FENETRE_SIGNAL_MS,
    dans_les_fenetres,
    fenetres_normalisees,
    load_observed_books,
)

JOUR_MS = 86_400_000


def _ecrire_carnets(tmp_path, instants):
    data_dir = tmp_path / "runtime" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "carnet_venues.jsonl").write_text(
        "\n".join(
            json.dumps({"coin": "BTC", "collecte_ts": instant / 1000.0, "hl_bid": 99.0,
                        "hl_ask": 101.0, "taille_min_usd": 1_000.0})
            for instant in instants
        ) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _instants(books):
    return sorted(ligne["ts_ms"] for lignes in books.values() for ligne in lignes)


# ----------------------------------------------------- 1. aucun changement par defaut
def test_sans_fenetres_le_comportement_est_INCHANGE(tmp_path):
    """Le defaut `None` doit laisser passer exactement ce qui passait avant."""
    _ecrire_carnets(tmp_path, (1_000, 2_000, 3_000))
    books, audit = load_observed_books(tmp_path)
    assert _instants(books) == [1_000, 2_000, 3_000]
    assert audit["fenetres_signal"] is None
    assert audit["hors_fenetres_signal_rejected"] == 0


# ----------------------------------------------------- 2. equivalence avec le plein
def test_EQUIVALENCE_avec_le_chargement_complet_dans_la_fenetre(tmp_path):
    """Le filtre ne doit retirer AUCUN carnet que le plein aurait retenu dans la fenetre.

    C'est la propriete qui autorise l'optimisation : memes reponses, moins de memoire.
    """
    signal = 10 * JOUR_MS
    # Des carnets dans la fenetre du signal, et beaucoup d'autres tres loin.
    dans = [signal - 25_000, signal - 10_000, signal - 1, signal]
    loin = [signal - 5 * JOUR_MS, signal - JOUR_MS, signal - 120_000, signal + 60_000]
    _ecrire_carnets(tmp_path, sorted(dans + loin))

    plein, audit_plein = load_observed_books(tmp_path, as_of_ms=signal)
    filtre, audit_filtre = load_observed_books(
        tmp_path, as_of_ms=signal, fenetres_signal_ms=[(signal, signal)])

    retenus_plein = set(_instants(plein))
    retenus_filtre = set(_instants(filtre))
    # Sous-ensemble : le filtre ne peut RIEN ajouter (donc aucun lookahead possible).
    assert retenus_filtre <= retenus_plein
    # Et il garde TOUT ce que le plein avait dans la fenetre : memes appariements.
    fenetre = fenetres_normalisees([(signal, signal)], marge_ms=MARGE_FENETRE_SIGNAL_MS)
    attendus = {ts for ts in retenus_plein if dans_les_fenetres(ts, fenetre)}
    assert retenus_filtre == attendus, (sorted(retenus_filtre), sorted(attendus))
    assert retenus_filtre == set(dans), sorted(retenus_filtre)
    # Le gain est mesure, pas suppose.
    assert len(retenus_filtre) < len(retenus_plein)
    assert audit_filtre["hors_fenetres_signal_rejected"] == len(retenus_plein) - len(retenus_filtre)
    assert audit_plein["hors_fenetres_signal_rejected"] == 0


# ----------------------------------------------------- 3. pas de lookahead
def test_un_carnet_POSTERIEUR_au_signal_reste_exclu(tmp_path):
    """La marge n'elargit que vers le passe : vers le futur elle ferait du lookahead."""
    signal = 10 * JOUR_MS
    _ecrire_carnets(tmp_path, (signal - 1_000, signal, signal + 1_000, signal + 29_000))
    books, _ = load_observed_books(tmp_path, fenetres_signal_ms=[(signal, signal)])
    retenus = _instants(books)
    assert retenus == [signal - 1_000, signal]
    assert all(ts <= signal for ts in retenus), "un carnet du futur est entre"


def test_la_marge_borne_exactement_trente_secondes(tmp_path):
    signal = 10 * JOUR_MS
    _ecrire_carnets(tmp_path, (signal - MARGE_FENETRE_SIGNAL_MS - 1,
                               signal - MARGE_FENETRE_SIGNAL_MS, signal))
    books, _ = load_observed_books(tmp_path, fenetres_signal_ms=[(signal, signal)])
    assert _instants(books) == [signal - MARGE_FENETRE_SIGNAL_MS, signal], \
        "la borne de la marge est INCLUSIVE, comme as_of_ms et depuis_ms"


# ----------------------------------------------------- 4. refus plutot que zero
def test_une_liste_de_fenetres_VIDE_est_un_REFUS(tmp_path):
    """Zero carnet ferait croire a un corpus sans carnets : un zero favorable, interdit."""
    _ecrire_carnets(tmp_path, (1_000, 2_000))
    with pytest.raises(ValueError, match="AUCUNE_FENETRE_DE_SIGNAL"):
        load_observed_books(tmp_path, fenetres_signal_ms=[])


def test_une_fenetre_INVERSEE_est_refusee():
    with pytest.raises(ValueError, match="FENETRE_INVERSEE"):
        fenetres_normalisees([(5_000, 1_000)])


# ----------------------------------------------------- 5. fusion et comptage
def test_des_signaux_PROCHES_ne_font_qu_une_fenetre():
    """Sans fusion, mille signaux rapproches feraient mille tests par ligne de carnet."""
    bornes = fenetres_normalisees([(1_000_000, 1_000_000), (1_000_100, 1_000_100)],
                                  marge_ms=MARGE_FENETRE_SIGNAL_MS)
    assert bornes == [(1_000_000 - MARGE_FENETRE_SIGNAL_MS, 1_000_100)]


def test_des_signaux_ELOIGNES_gardent_des_fenetres_distinctes():
    bornes = fenetres_normalisees([(10 * JOUR_MS, 10 * JOUR_MS), (12 * JOUR_MS, 12 * JOUR_MS)],
                                  marge_ms=MARGE_FENETRE_SIGNAL_MS)
    assert len(bornes) == 2


def test_les_lignes_ecartees_sont_COMPTEES(tmp_path):
    signal = 10 * JOUR_MS
    _ecrire_carnets(tmp_path, (signal - 5 * JOUR_MS, signal - JOUR_MS, signal))
    _, audit = load_observed_books(tmp_path, fenetres_signal_ms=[(signal, signal)])
    assert audit["hors_fenetres_signal_rejected"] == 2
    assert audit["fenetres_signal"] == 1
