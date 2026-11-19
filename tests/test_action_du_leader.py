"""Ouverture ou renforcement ? La question se LIT ou se REFUSE — jamais ne se suppose.

POURQUOI CE FICHIER EXISTE. C'était la cause racine du refus unanime du labo Copy-Vault, trouvée
le 19/11/2026 après deux jours de fausses pistes (plafond de carnets, mélange de connexions,
portes infranchissables — tous réels, aucun décisif).

La politique gelée ne copie que les renforcements (`NON_ADD_REJECTED` pour tout le reste).
Distinguer un renforcement d'une ouverture demande la position du leader AVANT le fill. Or :

  * `start_position` n'est renseigné que par la source `LIVE_WS` — **434 lignes sur 117 137** pour
    une heure, soit 0,4 % ;
  * la dérivation faisait `float(ligne.get("start_position") or 0.0)`, puis « ADD si non nul ».

Donc 99,6 % des fills étaient déclarés « ouvertures » alors que l'information n'existait pas, et
la politique les refusait tous. Mesure finale : **0 ADD sur 50 581 métaordres**, 0 candidat,
0 trade, 11 391 essais rejetés sans qu'aucune porte ne soit en cause.

Deux défauts se superposaient, et il fallait les deux :

  1. le `or 0.0`, qui transformait « on ne sait pas » en affirmation ;
  2. le MÊME fill rapporté deux fois — `LIVE_POLL` sans position, `LIVE_WS` avec — dont
     `cluster_metaorders` gardait la première venue. Les 915 renforcements réels de l'heure se
     faisaient écraser par leur jumeau ignorant.

Ce que ces tests verrouillent, dans cet ordre : une position inconnue se refuse et se compte ;
un doublon mieux renseigné corrige celui qu'il double ; un doublon moins renseigné ne dégrade
rien ; et la position se lit causalement, sans jamais regarder après le fill.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import coffre_tranches
from hl_observer.backtesting import copy_vault_coffre_vers_labo as pont


def _index(racine: Path) -> None:
    (racine / "runtime/coffre_certifie").mkdir(parents=True, exist_ok=True)
    (racine / "runtime/coffre_certifie/LOCAL_INDEX.json").write_text(
        json.dumps({"shards": [{"famille": "fills_forward", "shard": "s1",
                                "ts_min_ms": 0, "ts_max_ms": 10_000_000_000}]}),
        encoding="utf-8")


def _fill(**extra) -> dict:
    socle = {"coin": "BTC", "vault": "0xleader", "ts_ms": 1_000_000, "dir": "Open Long",
             "signe": 1, "px": 100.0, "sz": 2.0, "source": "LIVE_POLL"}
    socle.update(extra)
    return socle


def _lire(tmp_path: Path, monkeypatch, lignes: list[dict], positions=None):
    _index(tmp_path)
    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"retenus": [{"shard": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter(lignes))
    return pont.fills_du_coffre(tmp_path, debut_ms=0, fin_ms=10_000_000, positions=positions)


def test_une_position_inconnue_est_refusee_et_comptee(tmp_path: Path, monkeypatch) -> None:
    """LA régression à ne jamais laisser revenir : pas de `or 0.0` sur une mesure absente."""
    entrees, audit = _lire(tmp_path, monkeypatch, [_fill(hash="0xaaa")])

    assert entrees == [], "un fill dont on ignore la position du leader n'est pas une ouverture"
    assert audit["ecartes_position_inconnue"] == 1, "et le refus se COMPTE, sinon il est invisible"
    assert audit["actions"] == {}, "surtout pas d'OPEN inventé"


def test_une_position_declaree_decide_l_action(tmp_path: Path, monkeypatch) -> None:
    """Quand le fill porte la position, elle tranche : nulle = ouverture, non nulle = renforcement."""
    entrees, audit = _lire(tmp_path, monkeypatch, [
        _fill(hash="0xaaa", start_position=0.0, source="LIVE_WS"),
        _fill(hash="0xbbb", start_position=3.5, source="LIVE_WS", ts_ms=1_000_001),
    ])
    assert [e["action"] for e in entrees] == ["OPEN", "ADD"]
    assert audit["actions"] == {"OPEN": 1, "ADD": 1}
    assert audit["ecartes_position_inconnue"] == 0


def test_la_position_observee_renseigne_un_fill_qui_ne_la_porte_pas(
    tmp_path: Path, monkeypatch
) -> None:
    """La famille `position` du coffre répond là où `LIVE_POLL` se taît."""
    positions = {("0xleader", "BTC"): [(900_000, 4.25)]}
    entrees, audit = _lire(tmp_path, monkeypatch, [_fill(hash="0xaaa")], positions=positions)
    assert [e["action"] for e in entrees] == ["ADD"]
    assert audit["ecartes_position_inconnue"] == 0

    # Position observée NULLE : c'est une vraie ouverture, et ce n'est pas la même chose
    # qu'une position inconnue.
    entrees, _ = _lire(tmp_path, monkeypatch, [_fill(hash="0xaaa")],
                       positions={("0xleader", "BTC"): [(900_000, 0.0)]})
    assert [e["action"] for e in entrees] == ["OPEN"]


def test_une_position_trop_vieille_ne_renseigne_plus(tmp_path: Path, monkeypatch) -> None:
    """Les observations tombent toutes les 57 s en médiane : au-delà de 5 minutes, on ne sait plus."""
    trop_vieille = 1_000_000 - pont.MAX_AGE_POSITION_MS - 1
    entrees, audit = _lire(tmp_path, monkeypatch, [_fill(hash="0xaaa")],
                           positions={("0xleader", "BTC"): [(trop_vieille, 4.25)]})
    assert entrees == []
    assert audit["ecartes_position_inconnue"] == 1


def test_la_position_ne_regarde_jamais_apres_le_fill() -> None:
    """Lire une position postérieure, c'est lire l'avenir pour décider s'il faut copier."""
    series = {("0xleader", "BTC"): [(1_000_001, 9.0)]}
    assert pont.position_avant(
        series, vault="0xleader", coin="BTC", instant_ms=1_000_000) is None
    # Pile à l'instant du fill, en revanche, la position lui est bien antérieure.
    series = {("0xleader", "BTC"): [(1_000_000, 9.0)]}
    assert pont.position_avant(
        series, vault="0xleader", coin="BTC", instant_ms=1_000_000) == 9.0


def test_le_doublon_mieux_renseigne_corrige_celui_qu_il_double(
    tmp_path: Path, monkeypatch
) -> None:
    """LE SECOND défaut : `LIVE_POLL` arrive d'abord et sans position, `LIVE_WS` ensuite avec.

    Garder la première venue faisait sortir un `OPEN` là où le fill était un renforcement — et
    `cluster_metaorders` écartait ensuite l'autre comme doublon, donc l'information exacte était
    perdue sans trace. Un doublon n'ajoute jamais un fill ; il peut seulement en corriger un.
    """
    positions = {("0xleader", "BTC"): [(900_000, 0.0)]}   # le POLL conclurait « ouverture »
    entrees, audit = _lire(tmp_path, monkeypatch, [
        _fill(hash="0xaaa", source="LIVE_POLL"),
        _fill(hash="0xaaa", source="LIVE_WS", start_position=7.5),
    ], positions=positions)

    assert len(entrees) == 1, "le même fill ne compte qu'une fois"
    assert entrees[0]["action"] == "ADD", "la copie qui PORTE la position l'emporte"
    assert entrees[0]["source"] == "LIVE_WS"
    assert audit["doublons_de_hash"] == 1
    assert audit["doublons_plus_informatifs"] == 1
    assert audit["actions"] == {"ADD": 1}, "l'OPEN corrigé ne doit pas rester dans le compte"


def test_le_doublon_moins_renseigne_ne_degrade_rien(tmp_path: Path, monkeypatch) -> None:
    """Dans l'autre ordre, la copie informée doit survivre à l'arrivée de l'ignorante."""
    entrees, audit = _lire(tmp_path, monkeypatch, [
        _fill(hash="0xaaa", source="LIVE_WS", start_position=7.5),
        _fill(hash="0xaaa", source="LIVE_POLL"),
    ], positions={("0xleader", "BTC"): [(900_000, 0.0)]})

    assert len(entrees) == 1
    assert entrees[0]["action"] == "ADD"
    assert audit["doublons_de_hash"] == 1
    assert audit["doublons_plus_informatifs"] == 0
    assert audit["actions"] == {"ADD": 1}


def test_une_fermeture_ne_demande_aucune_position(tmp_path: Path, monkeypatch) -> None:
    """« Close Long » se lit dans le libellé : exiger une position la refuserait pour rien."""
    entrees, audit = _lire(tmp_path, monkeypatch, [
        _fill(hash="0xccc", dir="Close Long", signe=-1)])
    assert [e["action"] for e in entrees] == ["CLOSE"]
    assert audit["ecartes_position_inconnue"] == 0
