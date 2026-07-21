"""MAPPING PERP ↔ SPOT AVEC SA PROVENANCE (P1-4, 21/07).

L'appariement reposait sur une heuristique de nom, sans mémoire : une fois le choix fait,
rien ne disait d'où il venait. Preuve que ça casse : `base aberrante ×141` (BERA), `×3511`
(TRUMP) — le nom correspond, l'actif non.

Ce que ces tests verrouillent :
  * un stable n'est JAMAIS apparié à un perp (loi `couverture_meme_actif`) ;
  * la provenance distingue le CERTAIN de l'HEURISTIQUE — et ne ment pas ;
  * un appariement qui CHANGE sans décision est signalé comme un incident ;
  * aucun index n'est inventé : ce que l'API ne donne pas reste `None`.
"""
from __future__ import annotations

import pytest

from hl_observer.market.mapping_unit import (SOURCE_INCONNU, SOURCE_NOM_OFFICIEL,
                                             SOURCE_PREFIXE_UNIT, apparier,
                                             detecter_changement, indexer_metadonnees, resume,
                                             source_appariement)

META = {
    "tokens": [{"index": 0, "name": "USDC"}, {"index": 1, "name": "UBTC"},
               {"index": 2, "name": "HYPE"}, {"index": 3, "name": "PURR"},
               {"index": 4, "name": "UETH"}],
    "universe": [
        {"name": "@1", "index": 1, "tokens": [1, 0]},     # UBTC/USDC
        {"name": "@2", "index": 2, "tokens": [2, 0]},     # HYPE/USDC
        {"name": "PURR/USDC", "index": 3, "tokens": [3, 0]},
        {"name": "@9", "index": 9, "tokens": [4, 0]},     # UETH/USDC
        {"name": "casse", "tokens": [1]},                  # une seule jambe -> ignoree
    ],
}


def test_les_metadonnees_officielles_sont_indexees_sans_rien_deviner():
    idx = indexer_metadonnees(META)
    assert idx["tokens"][1] == "UBTC"
    assert idx["paires"]["@1"]["hypercore_token_name"] == "UBTC"
    assert idx["paires"]["@1"]["base_token_index"] == 1
    assert idx["paires"]["@1"]["quote_token_index"] == 0
    assert "casse" not in idx["paires"], "une paire sans deux jambes doit etre IGNOREE"


def test_metadonnees_absentes_ne_plantent_pas():
    for mauvais in (None, {}, {"tokens": None}, "pas un dict"):
        idx = indexer_metadonnees(mauvais)
        assert idx["tokens"] == {} and idx["paires"] == {}


# ------------------------------------------------------------------ la provenance

def test_un_nom_IDENTIQUE_est_certain():
    assert source_appariement("HYPE", "HYPE") == SOURCE_NOM_OFFICIEL


def test_un_token_UNIT_est_HEURISTIQUE_et_le_dit():
    """UBTC→BTC marche, mais c'est une règle de nom — pas une preuve d'identité d'actif."""
    assert source_appariement("BTC", "UBTC") == SOURCE_PREFIXE_UNIT
    assert source_appariement("ETH", "UETH") == SOURCE_PREFIXE_UNIT


@pytest.mark.parametrize("perp, token", [
    ("BTC", "USDC"), ("HYPE", "USDT"), ("SOL", "FEUSD"),      # stables : jamais
    ("BTC", "UET"),                                            # radical trop court
    ("TRUMP", "UBTC"),                                         # radical ne correspond pas
    ("", "UBTC"), ("BTC", ""),                                 # vides
])
def test_les_appariements_douteux_sont_INCONNUS(perp, token):
    assert source_appariement(perp, token) == SOURCE_INCONNU


def test_un_stable_n_est_JAMAIS_apparie():
    """Loi `couverture_meme_actif` : une couverture ne vaut que si c'est le MÊME actif."""
    for s in ("USDC", "USDT", "USDE", "FEUSD"):
        assert source_appariement("USDCPERP", s) == SOURCE_INCONNU


# ------------------------------------------------------------------ l'appariement complet

def test_l_appariement_porte_TOUS_les_champs_de_provenance():
    idx = indexer_metadonnees(META)
    m = apparier("BTC", "@1", idx, now_ms=1_760_000_000_000)
    for champ in ("display_symbol", "hypercore_token_name", "spot_pair_index",
                  "base_token_index", "quote_token_index", "perp_symbol",
                  "canonical_mapping", "mapping_source", "mapping_timestamp"):
        assert champ in m, "champ de provenance manquant : %s" % champ
    assert m["mapping_source"] == SOURCE_PREFIXE_UNIT
    assert m["certain"] is False
    assert m["canonical_mapping"] == "BTC<-@1"


def test_un_nom_officiel_est_marque_CERTAIN():
    m = apparier("HYPE", "@2", indexer_metadonnees(META))
    assert m["mapping_source"] == SOURCE_NOM_OFFICIEL and m["certain"] is True


def test_une_paire_inconnue_ne_produit_AUCUN_appariement():
    assert apparier("BTC", "@999", indexer_metadonnees(META)) is None


def test_un_appariement_sans_regle_rend_None_plutot_qu_un_faux():
    """Mieux vaut un appariement manquant qu'un appariement inventé."""
    assert apparier("TRUMP", "@1", indexer_metadonnees(META)) is None


# ------------------------------------------------------------------ le changement silencieux

def test_un_appariement_qui_CHANGE_est_un_incident():
    """C'est ce qui a produit `base aberrante ×3511` sur TRUMP : la paire choisie n'était
    plus la même, et rien ne l'avait signalé."""
    idx = indexer_metadonnees(META)
    avant = apparier("BTC", "@1", idx)
    apres = apparier("ETH", "@9", idx)
    inc = detecter_changement(avant, apres)
    assert inc is not None
    assert inc["avant"] == "BTC<-@1" and inc["apres"] == "ETH<-@9"


def test_aucun_changement_ne_produit_AUCUNE_alerte():
    """Un registre qui crie tout le temps finit par ne plus être lu."""
    idx = indexer_metadonnees(META)
    m = apparier("BTC", "@1", idx)
    assert detecter_changement(m, m) is None
    assert detecter_changement(None, m) is None and detecter_changement(m, None) is None


# ------------------------------------------------------------------ la proportion qui compte

def test_le_resume_dit_QUELLE_PART_est_certaine():
    """Un projet qui ne sait pas cette proportion ne sait pas ce qu'il trade."""
    idx = indexer_metadonnees(META)
    r = resume([apparier("HYPE", "@2", idx), apparier("BTC", "@1", idx),
                apparier("ETH", "@9", idx)])
    assert r["total"] == 3 and r["certains"] == 1 and r["heuristiques"] == 2
    assert r["part_certaine_pct"] == pytest.approx(33.3, abs=0.1)
    assert set(r["coins_heuristiques"]) == {"BTC", "ETH"}


def test_le_resume_vide_ne_ment_pas():
    r = resume([])
    assert r["total"] == 0 and r["part_certaine_pct"] is None


# ------------------------------------------------------------------ testé ≠ branché

def test_la_provenance_est_BRANCHEE_dans_le_feeder():
    """Sans ça, le module resterait un test de plus dans le limbe — 28,6 % du projet."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "tools"
           / "ecrire_carry_spot_inputs.py").read_text(encoding="utf-8")
    assert "mapping_unit" in src
    assert "indexer_metadonnees" in src and "mapping_source" in src


def test_la_provenance_est_ENREGISTREE_dans_le_journal_de_scans():
    """Un appariement heuristique doit rester identifiable dans l'historique, sinon on ne
    pourra jamais rattacher une anomalie de base à un mauvais mapping."""
    from hl_observer.backtesting.carry_scan_recorder import CHAMPS_TEXTE, normaliser
    assert "mapping_source" in CHAMPS_TEXTE and "canonical_mapping" in CHAMPS_TEXTE
    l = normaliser({"coin": "BTC", "mapping_source": "PREFIXE_UNIT",
                    "canonical_mapping": "BTC<-@1"}, ts_ms=1)
    assert l["mapping_source"] == "PREFIXE_UNIT" and l["canonical_mapping"] == "BTC<-@1"
