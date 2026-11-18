"""La phase 1 lit les carnets du COFFRE, filtre en flux, et ne mentit pas sur ce qu'elle écarte.

POURQUOI CE CHEMIN EXISTE. Mesure du 18/11/2026 : `load_observed_books` lit
`runtime/data/*.jsonl`, dont le ruban L2 ne commence qu'au **17/11 18:35**. Le coffre certifié
porte `bbo` et `book_l2` depuis le **26/10**. Branchée sur les rubans locaux, la phase 1 préparait
donc du vide pour toute tranche antérieure au 17/11, en rendant honnêtement « 0 carnet » — ce qui
se lit « pas de données » alors que la cause était « pas regardé au bon endroit ». Sur la tranche
t001 (13/11 00:00), le passage au coffre fait **0 → 23 046 carnets**.

Ce que ces tests protègent :

  * le coffre absent se DIT (`COFFRE_ABSENT`) au lieu de rendre un dictionnaire vide qu'on lirait
    comme « aucun carnet » ;
  * la fenêtre causale est élargie côté passé (`debut_ms - fenetre_ms`) : un carnet d'avant le
    début de tranche peut renseigner un signal du tout début, et l'oublier perdrait des signaux ;
  * le filtrage se fait EN FLUX : seuls les carnets retenus sont matérialisés, sinon l'économie de
    la phase 1 serait perdue d'avance ;
  * l'audit distingue ce qui a été LU de ce qui a été GARDÉ, par famille — c'est la seule façon de
    distinguer « rien à lire » de « je n'ai pas su lire ».
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl_observer.backtesting import coffre_tranches
from hl_observer.backtesting import copy_vault_labo_deux_phases as deux_phases
from hl_observer.backtesting.copy_vault_signal_alignment import MAX_BOOK_AGE_MS


def _index(tmp_path: Path, shards: list[dict[str, Any]]) -> Path:
    chemin = tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"shards": shards}), encoding="utf-8")
    return chemin


def test_un_coffre_absent_est_dit_et_non_confondu_avec_un_corpus_vide(tmp_path: Path) -> None:
    """« COFFRE_ABSENT » et « aucun carnet » doivent être deux réponses distinctes.

    Rendre un dictionnaire vide sans motif laisserait croire que le corpus ne contient rien, alors
    que l'index n'a simplement pas été trouvé — l'erreur la plus coûteuse de la journée.
    """
    carnets, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=0, fin_ms=1_000)
    assert carnets == {}
    assert audit["status"] == "COFFRE_ABSENT"
    assert "LOCAL_INDEX.json" in audit["chemin"]


def test_les_carnets_hors_portee_d_un_signal_ne_sont_pas_materialises(
    tmp_path: Path, monkeypatch
) -> None:
    """Le filtrage est EN FLUX : un carnet hors fenêtre est lu, compté, et jamais garde."""
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    signal = 1_000_000
    lignes = [
        {"coin": "BTC", "ts_ms": signal - 10, "bid": 1.0},                      # garde
        {"coin": "BTC", "ts_ms": signal - MAX_BOOK_AGE_MS, "bid": 1.0},         # garde (borne)
        {"coin": "BTC", "ts_ms": signal - MAX_BOOK_AGE_MS - 1, "bid": 1.0},     # ecarte
        {"coin": "BTC", "ts_ms": signal + 1, "bid": 1.0},                       # ecarte (futur)
    ]

    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    monkeypatch.setattr(coffre_tranches, "flux",
                        lambda *a, **k: iter(lignes if k.get("famille") == "book_l2" else []))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=signal - 100_000, fin_ms=signal,
        familles=("book_l2",), instants_par_coin={"BTC": [signal]})

    assert audit["status"] == "LU_DEPUIS_LE_COFFRE"
    assert audit["lignes_lues"] == 4, "les 4 lignes ont bien ete traversees"
    assert audit["carnets_gardes"] == 2, "seules les 2 a portee du signal sont materialisees"
    assert [c["ts_ms"] for c in gardes["BTC"]] == [signal - MAX_BOOK_AGE_MS, signal - 10]
    assert audit["familles"]["book_l2"] == {"shards": 1, "lus": 4, "gardes": 2}


def test_l_audit_distingue_les_lignes_lues_des_carnets_gardes(tmp_path: Path, monkeypatch) -> None:
    """Sans ce couple, « 0 garde » ne se distingue pas de « 0 lu » — le piège du zéro muet."""
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    # Des lignes lues, AUCUNE a portee : lues > 0 et gardes == 0.
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter(
        [{"coin": "BTC", "ts_ms": 10}, {"coin": "BTC", "ts_ms": 20}]))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=5_000_000, fin_ms=6_000_000,
        familles=("book_l2",), instants_par_coin={"BTC": [5_500_000]})

    assert gardes == {}
    assert audit["lignes_lues"] == 2, "on a bien LU : ce n'est pas « rien a lire »"
    assert audit["carnets_gardes"] == 0


def test_la_fenetre_est_elargie_vers_le_passe_a_la_selection(tmp_path: Path, monkeypatch) -> None:
    """Un carnet d'AVANT le debut de tranche peut renseigner un signal du tout debut.

    Si la selection demandait `debut_ms` tout court, ce carnet ne serait jamais lu et le premier
    signal de chaque tranche perdrait son contexte -- un signal perdu par tranche, 33 fois.
    """
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    vus: dict[str, Any] = {}

    def selectionner(_shards, **kw):
        vus.update(kw)
        return {"shards": [{"id": "s1"}]}

    monkeypatch.setattr(coffre_tranches, "selectionner", selectionner)
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter([]))

    debut = 1_000_000
    deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=debut, fin_ms=debut + 1_000,
        familles=("book_l2",))

    assert vus["debut_ms"] == debut - MAX_BOOK_AGE_MS, (
        "la selection doit remonter d'une fenetre causale avant le debut de tranche")


def test_les_familles_de_carnets_couvrent_le_coffre_reel() -> None:
    """Les familles visées sont celles que le coffre porte vraiment (mesure du 18/11/2026).

    `bbo` (111,9 M lignes) et `book_l2` (9,6 M) remontent au 26/10 ; `micro_bbo`, `micro_l2` et
    `venue_book` complètent. En oublier une rendrait des tranches artificiellement pauvres.
    """
    assert set(deux_phases.FAMILLES_DE_CARNETS) == {
        "book_l2", "micro_l2", "venue_book", "bbo", "micro_bbo",
    }
