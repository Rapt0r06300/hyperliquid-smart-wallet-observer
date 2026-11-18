"""LA BORNE BASSE DES CARNETS : conduire le replay jour par jour, sans charger six jours d'un coup.

MESURE DU 18/11/2026 sur le ruban L2 réellement produit par le labo : 7 527 878 carnets sur douze
jours, dont SIX denses (13 au 18/11, de 1,3 à 1,8 million chacun) — exactement le nombre de jours
que le labo exige pour conclure. Un jour tient en mémoire (~2,4 Go en moyenne), les six ensemble
non (~28 Go), et c'est ce chargement global qui a fait couper le rejeu à l'étape 2.

`as_of_ms` existait seule : on pouvait demander « avant tel instant », jamais « entre deux ». Ces
tests verrouillent la borne basse, son inclusivité, son refus d'une fenêtre vide, et le fait qu'un
carnet écarté par elle est COMPTÉ et non oublié.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting.copy_vault_book_loader import load_observed_books


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


def test_sans_borne_basse_tous_les_carnets_entrent(tmp_path):
    _ecrire_carnets(tmp_path, (1_000, 2_000, 3_000))
    books, audit = load_observed_books(tmp_path)
    assert _instants(books) == [1_000, 2_000, 3_000]
    assert audit["depuis_ms"] is None and audit["past_rows_rejected"] == 0


def test_la_borne_basse_ECARTE_les_carnets_anterieurs_et_les_COMPTE(tmp_path):
    _ecrire_carnets(tmp_path, (1_000, 2_000, 3_000))
    books, audit = load_observed_books(tmp_path, depuis_ms=2_000)
    assert _instants(books) == [2_000, 3_000], "la borne basse est INCLUSIVE"
    assert audit["depuis_ms"] == 2_000 and audit["past_rows_rejected"] == 1, \
        "un carnet hors fenêtre est compté, jamais oublié en silence"


def test_les_DEUX_bornes_decoupent_une_journee(tmp_path):
    """L'usage visé : un jour à la fois, pour que six jours ne demandent pas 28 Go."""
    jour = 86_400_000
    _ecrire_carnets(tmp_path, (jour - 1, jour, jour + 5_000, 2 * jour, 2 * jour + 1))
    books, audit = load_observed_books(tmp_path, depuis_ms=jour, as_of_ms=2 * jour - 1)
    assert _instants(books) == [jour, jour + 5_000]
    assert audit["past_rows_rejected"] == 1 and audit["future_rows_rejected"] == 2


def test_une_fenetre_VIDE_est_REFUSEE_et_non_rendue_vide(tmp_path):
    """Rendre zéro carnet pour une fenêtre absurde ferait lire « aucune donnée » au lieu d'une erreur."""
    _ecrire_carnets(tmp_path, (1_000,))
    with pytest.raises(ValueError, match="fenetre de carnets vide"):
        load_observed_books(tmp_path, depuis_ms=5_000, as_of_ms=4_999)


def test_les_deux_bornes_EGALES_gardent_l_instant_exact(tmp_path):
    _ecrire_carnets(tmp_path, (999, 1_000, 1_001))
    books, audit = load_observed_books(tmp_path, depuis_ms=1_000, as_of_ms=1_000)
    assert _instants(books) == [1_000]
    assert audit["past_rows_rejected"] == 1 and audit["future_rows_rejected"] == 1


def test_une_borne_basse_INVALIDE_est_refusee(tmp_path):
    _ecrire_carnets(tmp_path, (1_000,))
    for mauvaise in (0, -1, 1.5, "1000", True):
        with pytest.raises((ValueError, TypeError)):
            load_observed_books(tmp_path, depuis_ms=mauvaise)


def test_la_borne_basse_est_appliquee_a_la_FRONTIERE_de_la_source():
    """Un appelant qui l'oublierait plus loin ne doit pas pouvoir faire entrer un carnet hors fenêtre."""
    import inspect

    from hl_observer.backtesting import copy_vault_book_loader as BL

    source = inspect.getsource(BL.load_observed_books)
    assert "if depuis_ms is not None and ts_ms < depuis_ms:" in source
    assert source.index("depuis_ms is not None and ts_ms < depuis_ms") < source.index('"depuis_ms": depuis_ms')


def test_la_fenetre_est_PUBLIEE_dans_l_audit(tmp_path):
    """Le labo publie ce qu'il a lu : une fenêtre non déclarée serait une mesure sans dénominateur."""
    _ecrire_carnets(tmp_path, (1_000, 2_000))
    _books, audit = load_observed_books(tmp_path, depuis_ms=1_500, as_of_ms=9_000)
    assert audit["depuis_ms"] == 1_500 and audit["as_of_ms"] == 9_000
