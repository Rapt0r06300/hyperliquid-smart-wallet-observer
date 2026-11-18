"""Le labo en deux phases : la phase 1 allege sans perdre, la phase 2 refuse de deviner.

Ce qui est verifie ici, et pourquoi chaque point compte :

  * la fenetre causale est respectee AUX BORNES, dans les deux sens -- un carnet garde en trop
    coute de la memoire, un carnet jete en trop fait disparaitre un signal sans que personne le
    voie. Le second est un faux resultat, le premier une lenteur ;
  * l'equation de conservation : vus = gardes + ecartes, par motif. Sans elle, « 0 carnet garde »
    et « 0 carnet lu » se ressemblent ;
  * la phase 2 REFUSE un dossier incomplet ou modifie. Charger neuf tranches sur dix donnerait un
    corpus silencieusement plus petit -- exactement le genre de resultat qu'on cherche a empecher ;
  * l'equivalence : preparer en deux tranches puis fusionner doit rendre le MEME corpus qu'une
    seule passe. C'est la promesse de l'architecture ; si elle est fausse, tout le reste est faux.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.backtesting.copy_vault_labo_deux_phases import (
    FICHIER_CARNETS,
    FICHIER_METAORDRES,
    MANIFESTE,
    TranchePreparéeInvalide,
    carnets_utiles,
    charger_tranches_preparees,
    preparer_tranche,
)
from hl_observer.backtesting.copy_vault_signal_alignment import MAX_BOOK_AGE_MS


def _ordre(coin: str, ts: int, *, side: str = "long", notional: str = "40") -> dict:
    return {"coin": coin, "signal_ts_ms": ts, "side": side, "notional_usd": notional}


def _carnet(ts: int, *, bid: float = 100.0, ask: float = 100.1) -> dict:
    return {"ts_ms": ts, "bid": bid, "ask": ask, "bid_sz": 1.0, "ask_sz": 1.0}


# --------------------------------------------------------------------------- la fenetre causale

def test_un_carnet_juste_dans_la_fenetre_est_garde() -> None:
    """La borne est INCLUSE, comme dans l'alignement : exactement `MAX_BOOK_AGE_MS` avant."""
    signal = 1_000_000
    gardes, audit = carnets_utiles(
        [_ordre("BTC", signal)],
        {"BTC": [_carnet(signal - MAX_BOOK_AGE_MS)]},
    )
    assert audit["carnets_gardes"] == 1, "un carnet pile a la limite doit etre garde"
    assert gardes["BTC"][0]["ts_ms"] == signal - MAX_BOOK_AGE_MS


def test_un_carnet_juste_hors_fenetre_est_ecarte() -> None:
    """L'AUTRE SENS : une milliseconde de trop et le carnet ne peut plus servir."""
    signal = 1_000_000
    _, audit = carnets_utiles(
        [_ordre("BTC", signal)],
        {"BTC": [_carnet(signal - MAX_BOOK_AGE_MS - 1)]},
    )
    assert audit["carnets_gardes"] == 0
    assert audit["ecartes_hors_fenetre"] == 1


def test_un_carnet_posterieur_au_signal_est_ecarte() -> None:
    """Un carnet d'APRES le signal ne peut pas le renseigner : ce serait lire l'avenir."""
    signal = 1_000_000
    _, audit = carnets_utiles([_ordre("BTC", signal)], {"BTC": [_carnet(signal + 1)]})
    assert audit["carnets_gardes"] == 0
    assert audit["ecartes_hors_fenetre"] == 1


def test_un_carnet_pile_sur_le_signal_est_garde() -> None:
    signal = 1_000_000
    _, audit = carnets_utiles([_ordre("BTC", signal)], {"BTC": [_carnet(signal)]})
    assert audit["carnets_gardes"] == 1


def test_les_carnets_d_un_coin_sans_signal_sont_ecartes_avec_leur_motif() -> None:
    """Et le motif est NOMME : « 0 garde » sans raison ne distingue pas de « 0 lu »."""
    gardes, audit = carnets_utiles(
        [_ordre("BTC", 1_000_000)],
        {"BTC": [_carnet(1_000_000)], "DOGE": [_carnet(1_000_000), _carnet(999_999)]},
    )
    assert set(gardes) == {"BTC"}
    assert audit["ecartes_coin_sans_signal"] == 2
    assert audit["coins_sans_signal"] == {"DOGE": 2}


def test_l_equation_de_conservation_est_toujours_bouclee() -> None:
    """vus = gardes + hors fenetre + coins sans signal. Rien ne disparait sans motif."""
    signal = 5_000_000
    carnets = {
        "BTC": [_carnet(signal - 1), _carnet(signal - MAX_BOOK_AGE_MS * 3), _carnet(signal + 5)],
        "ETH": [_carnet(signal - 10)],
        "SOL": [_carnet(signal), _carnet(signal - 2)],
    }
    _, audit = carnets_utiles([_ordre("BTC", signal), _ordre("ETH", signal)], carnets)
    assert audit["non_explique"] == 0, audit
    assert (
        audit["carnets_vus"]
        == audit["carnets_gardes"]
        + audit["ecartes_hors_fenetre"]
        + audit["ecartes_coin_sans_signal"]
    )


def test_plusieurs_signaux_partagent_leurs_carnets() -> None:
    """Un carnet utile a DEUX signaux n'est garde qu'une fois, et pas perdu pour autant."""
    gardes, audit = carnets_utiles(
        [_ordre("BTC", 1_000_000), _ordre("BTC", 1_000_005)],
        {"BTC": [_carnet(999_999)]},
    )
    assert audit["carnets_gardes"] == 1
    assert len(gardes["BTC"]) == 1


# ------------------------------------------------------------------------------------- phase 1

def test_la_phase_1_ecrit_ses_rubans_et_un_manifeste_avec_empreintes(tmp_path: Path) -> None:
    manifeste = preparer_tranche(
        metaordres=[_ordre("BTC", 1_000_000), _ordre("ETH", 1_000_100)],
        carnets={"BTC": [_carnet(999_990)], "ETH": [_carnet(1_000_090)]},
        sortie=tmp_path / "t01",
        tranche=(900_000, 1_100_000),
        identite="t01",
    )
    for nom in (MANIFESTE, FICHIER_METAORDRES, FICHIER_CARNETS):
        assert (tmp_path / "t01" / nom).exists(), nom
    assert manifeste["metaordres"] == 2
    assert manifeste["signal_ts_min_ms"] == 1_000_000
    assert manifeste["signal_ts_max_ms"] == 1_000_100
    assert len(manifeste["sha256_metaordres"]) == 64
    assert len(manifeste["sha256_carnets"]) == 64
    assert manifeste["audit_carnets"]["non_explique"] == 0


def test_la_phase_1_ne_juge_rien(tmp_path: Path) -> None:
    """Pas de verdict, pas de PnL, pas de champion : elle transporte et compte.

    Un morceau qui jugerait l'ensemble est precisement le defaut que cette architecture evite.
    """
    manifeste = preparer_tranche(
        metaordres=[_ordre("BTC", 1_000_000)],
        carnets={"BTC": [_carnet(999_990)]},
        sortie=tmp_path / "t01",
    )
    interdits = {"status", "verdict", "economically_proven", "pnl", "champion", "candidates_tested"}
    assert interdits.isdisjoint(manifeste), interdits & set(manifeste)


def test_les_rubans_sont_ecrits_en_sauts_de_ligne_unix(tmp_path: Path) -> None:
    """Sous Windows, une conversion CRLF changerait l'empreinte relue par la phase 2."""
    preparer_tranche(
        metaordres=[_ordre("BTC", 1_000_000)],
        carnets={"BTC": [_carnet(999_990)]},
        sortie=tmp_path / "t01",
    )
    brut = (tmp_path / "t01" / FICHIER_METAORDRES).read_bytes()
    assert b"\r\n" not in brut
    assert brut.endswith(b"\n")


# ------------------------------------------------------------------------------------- phase 2

def _deux_tranches(racine: Path) -> None:
    preparer_tranche(
        metaordres=[_ordre("BTC", 1_000), _ordre("BTC", 2_000)],
        carnets={"BTC": [_carnet(1_000), _carnet(2_000)]},
        sortie=racine / "t01", identite="t01", tranche=(0, 2_500),
    )
    preparer_tranche(
        metaordres=[_ordre("BTC", 3_000), _ordre("ETH", 4_000)],
        carnets={"BTC": [_carnet(3_000)], "ETH": [_carnet(4_000)]},
        sortie=racine / "t02", identite="t02", tranche=(2_500, 5_000),
    )


def test_la_phase_2_fusionne_les_tranches_dans_l_ordre(tmp_path: Path) -> None:
    _deux_tranches(tmp_path)
    metaordres, carnets, audit = charger_tranches_preparees(tmp_path)
    assert audit["tranches_chargees"] == 2
    assert [o["signal_ts_ms"] for o in metaordres] == [1_000, 2_000, 3_000, 4_000]
    assert set(carnets) == {"BTC", "ETH"}
    assert [c["ts_ms"] for c in carnets["BTC"]] == [1_000, 2_000, 3_000]
    assert audit["signal_ts_min_ms"] == 1_000
    assert audit["signal_ts_max_ms"] == 4_000


def test_la_phase_2_ecarte_les_doublons_de_recouvrement(tmp_path: Path) -> None:
    """Deux tranches voisines peuvent se recouvrir ; compter deux fois gonflerait le corpus."""
    preparer_tranche(metaordres=[_ordre("BTC", 1_000)], carnets={"BTC": [_carnet(1_000)]},
                     sortie=tmp_path / "t01", identite="t01")
    preparer_tranche(metaordres=[_ordre("BTC", 1_000)], carnets={"BTC": [_carnet(1_000)]},
                     sortie=tmp_path / "t02", identite="t02")
    metaordres, _, audit = charger_tranches_preparees(tmp_path)
    assert len(metaordres) == 1
    assert audit["metaordres_doublons_ecartes"] == 1


def test_la_phase_2_refuse_un_manifeste_absent(tmp_path: Path) -> None:
    _deux_tranches(tmp_path)
    (tmp_path / "t02" / MANIFESTE).unlink()
    with pytest.raises(TranchePreparéeInvalide, match="manifeste absent"):
        charger_tranches_preparees(tmp_path)


def test_la_phase_2_refuse_un_ruban_modifie_apres_la_phase_1(tmp_path: Path) -> None:
    """L'empreinte protege contre une tranche retouchee entre les deux passes."""
    _deux_tranches(tmp_path)
    cible = tmp_path / "t02" / FICHIER_METAORDRES
    with open(cible, "ab") as flux:
        flux.write(json.dumps(_ordre("DOGE", 9_999)).encode("utf-8") + b"\n")
    with pytest.raises(TranchePreparéeInvalide, match="modifie depuis la phase 1"):
        charger_tranches_preparees(tmp_path)


def test_la_phase_2_refuse_un_format_inconnu(tmp_path: Path) -> None:
    _deux_tranches(tmp_path)
    chemin = tmp_path / "t02" / MANIFESTE
    manifeste = json.loads(chemin.read_bytes().splitlines()[0])
    manifeste["format_version"] = 99
    with open(chemin, "wb") as flux:
        flux.write(json.dumps(manifeste, separators=(",", ":"), sort_keys=True).encode() + b"\n")
    with pytest.raises(TranchePreparéeInvalide, match="format 99"):
        charger_tranches_preparees(tmp_path)


def test_la_phase_2_refuse_un_dossier_vide(tmp_path: Path) -> None:
    with pytest.raises(TranchePreparéeInvalide, match="aucune tranche preparee"):
        charger_tranches_preparees(tmp_path / "rien")


# ------------------------------------------------------- la promesse de l'architecture

def test_deux_tranches_rendent_le_meme_corpus_qu_une_seule_passe(tmp_path: Path) -> None:
    """L'EQUIVALENCE : decouper puis fusionner ne doit rien changer.

    C'est la promesse de l'architecture en deux phases. Si elle est fausse, le PnL mesure sur le
    corpus fusionne ne vaut rien -- et il vaudrait mieux ne pas le calculer du tout.
    """
    ordres = [_ordre("BTC", 1_000), _ordre("BTC", 2_000), _ordre("BTC", 3_000),
              _ordre("ETH", 4_000)]
    carnets = {
        "BTC": [_carnet(1_000), _carnet(2_000), _carnet(3_000)],
        "ETH": [_carnet(4_000)],
    }

    # en une passe
    preparer_tranche(metaordres=ordres, carnets=carnets,
                     sortie=tmp_path / "entier" / "tout", identite="tout")
    ref_ordres, ref_carnets, _ = charger_tranches_preparees(tmp_path / "entier")

    # en deux tranches disjointes
    coupe = tmp_path / "coupe"
    preparer_tranche(
        metaordres=[o for o in ordres if o["signal_ts_ms"] <= 2_000],
        carnets={"BTC": [c for c in carnets["BTC"] if c["ts_ms"] <= 2_000]},
        sortie=coupe / "t01", identite="t01",
    )
    preparer_tranche(
        metaordres=[o for o in ordres if o["signal_ts_ms"] > 2_000],
        carnets={"BTC": [c for c in carnets["BTC"] if c["ts_ms"] > 2_000],
                 "ETH": list(carnets["ETH"])},
        sortie=coupe / "t02", identite="t02",
    )
    vus_ordres, vus_carnets, audit = charger_tranches_preparees(coupe)

    assert vus_ordres == ref_ordres, "un signal a ete perdu ou invente par le decoupage"
    assert vus_carnets == ref_carnets, "un carnet a ete perdu ou invente par le decoupage"
    assert audit["metaordres"] == len(ordres)
