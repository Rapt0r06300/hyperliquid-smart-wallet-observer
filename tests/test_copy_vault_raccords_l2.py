"""Raccord des connexions L2 : franchir un trou COURT, jamais un trou long, et tout compter.

La règle touche le cœur causal du replay. Elle doit donc rester éteinte par défaut, ne jamais
fabriquer de continuité au-delà du seuil que le labo s'impose déjà, et publier ce qu'elle a franchi
et refusé — sans quoi on ne saurait pas sur quelle part du ruban repose un verdict.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.backtesting import copy_vault_raccords_l2 as R
from hl_observer.backtesting.copy_vault_protocol import MAX_TARGET_LAG_MS


def _c(ts: int, connexion: str) -> dict:
    return {"ts_ms": ts, "connection_id": connexion, "bid": 1.0, "ask": 1.1}


def test_le_seuil_est_celui_que_le_labo_s_impose_deja() -> None:
    carnets, audit = R.raccorder_les_connexions({"BTC": [_c(0, "A")]})
    assert audit["trou_max_ms"] == MAX_TARGET_LAG_MS == 30_000 and audit["chaines"] == 1


def test_un_trou_court_entre_deux_connexions_est_franchi_et_compte() -> None:
    carnets, audit = R.raccorder_les_connexions({"BTC": [_c(0, "A"), _c(1_000, "A"), _c(3_840, "B"), _c(5_000, "B")]})
    assert {c["connection_id"] for c in carnets["BTC"]} == {"chaine:BTC:0"}        # une seule chaîne
    assert [c["connection_id_observee"] for c in carnets["BTC"]] == ["A", "A", "B", "B"]   # l'origine est gardée
    assert audit["raccords_franchis"] == 1 and audit["raccords_refuses"] == 0
    assert audit["trou_franchi_median_ms"] == 2_840


def test_un_trou_long_reste_une_rupture_meme_d_une_milliseconde_de_trop() -> None:
    juste, _ = R.raccorder_les_connexions({"BTC": [_c(0, "A"), _c(30_000, "B")]})
    assert len({c["connection_id"] for c in juste["BTC"]}) == 1                     # 30 000 ms : franchi
    carnets, audit = R.raccorder_les_connexions({"BTC": [_c(0, "A"), _c(30_001, "B")]})
    assert [c["connection_id"] for c in carnets["BTC"]] == ["chaine:BTC:0", "chaine:BTC:1"]
    assert audit["raccords_franchis"] == 0 and audit["raccords_refuses"] == 1
    assert audit["plus_long_trou_refuse_ms"] == 30_001


def test_un_silence_long_sur_la_MEME_connexion_casse_aussi_la_chaine() -> None:
    """Une identité de socket constante ne prouve rien si rien n'a été observé pendant une minute."""
    carnets, audit = R.raccorder_les_connexions({"BTC": [_c(0, "A"), _c(60_000, "A")]})
    assert len({c["connection_id"] for c in carnets["BTC"]}) == 2
    assert audit["raccords_franchis"] == 0 and audit["raccords_refuses"] == 0       # pas un raccord : un silence


def test_des_connexions_entrelacees_ne_perdent_aucun_carnet() -> None:
    entrelaces = [_c(t, "A" if i % 2 else "B") for i, t in enumerate(range(0, 20_000, 1_000))]
    carnets, audit = R.raccorder_les_connexions({"ETH": list(reversed(entrelaces))})   # donnés à l'envers
    assert len(carnets["ETH"]) == 20 and audit["carnets_gardes"] == 20 and audit["chaines"] == 1
    assert [c["ts_ms"] for c in carnets["ETH"]] == sorted(c["ts_ms"] for c in entrelaces)


def test_les_coins_ne_se_melangent_pas_et_un_carnet_sans_horodatage_est_compte() -> None:
    carnets, audit = R.raccorder_les_connexions({"BTC": [_c(0, "A")], "ETH": [_c(0, "A"), {"connection_id": "A"}]})
    assert carnets["BTC"][0]["connection_id"] != carnets["ETH"][0]["connection_id"]
    assert audit["carnets_sans_horodatage"] == 1 and audit["carnets_gardes"] == 2


def test_la_regle_est_eteinte_par_defaut_et_ne_s_allume_que_sur_demande_explicite(monkeypatch) -> None:
    monkeypatch.delenv(R.VARIABLE, raising=False)
    assert R.raccord_demande() is False
    for valeur, attendu in (("1", True), ("0", False), ("true", False), ("", False)):
        monkeypatch.setenv(R.VARIABLE, valeur)
        assert R.raccord_demande() is attendu
    source = Path(R.__file__).with_name("copy_vault_labo_deux_phases.py").read_text(encoding="utf-8")
    assert source.index("if raccord_demande():") < source.index("carnets, audit_connexion = une_seule_connexion_par_coin(carnets)")


def test_apres_raccord_la_regle_d_origine_ne_jette_plus_les_carnets_eparpilles() -> None:
    """Le cas mesuré : un coin vu par deux sockets qui se relaient. Sans raccord, la règle d'origine
    garde une seule des deux connexions qui se recouvrent ; avec, elle garde tout."""
    from hl_observer.backtesting.copy_vault_coffre_vers_labo import une_seule_connexion_par_coin

    relais = [_c(t, "A") for t in range(0, 10_000, 1_000)] + [_c(t, "B") for t in range(500, 10_500, 1_000)]
    _, sans = une_seule_connexion_par_coin({"SOL": relais})
    raccordes, _ = R.raccorder_les_connexions({"SOL": relais})
    _, avec = une_seule_connexion_par_coin(raccordes)
    assert sans["carnets_gardes"] == 10 and sans["ecartes_connexion_minoritaire"] == 10
    assert avec["carnets_gardes"] == 20 and avec["ecartes_connexion_minoritaire"] == 0


def test_la_session_locale_des_carnets_dure_plus_longtemps_que_le_plus_long_horizon_du_labo() -> None:
    """Mesure du 22/11/2026 : avec des sessions de 25 minutes, aucun épisode de plus de 25 minutes
    ne pouvait tenir sur une seule connexion. La session locale doit couvrir largement l'horizon."""
    from hl_observer.ops.collecteur_registry import REGISTRE

    lane = next(c for c in REGISTRE if c["nom"] == "l2-leaders")
    arguments = list(lane["args"])
    duree_s = float(arguments[arguments.index("--duree-s") + 1])
    horizon_max_du_labo_s = 3_600.0
    assert duree_s >= 4 * horizon_max_du_labo_s, duree_s
