"""Étape 2/3 — capacité jointe aux épisodes, sans lookahead.

Le test qui compte : `test_un_carnet_posterieur_nest_jamais_choisi`. Prendre le carnet le plus PROCHE
plutôt que le dernier ANTÉRIEUR donnerait au décideur une liquidité qu'il ne pouvait pas connaître — un
lookahead déguisé en mesure de capacité.

Paper only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import episode_capacity as CAP  # noqa: E402
from hl_observer.ops.economic_revalidation import Episode  # noqa: E402

T0 = 1_700_000_000_000


def _index(paires, coin="BTC"):
    return {coin: {"ts": [p[0] for p in paires], "taille": [p[1] for p in paires]}}


def _episode(ts=T0, notional=1_000.0, coin="BTC"):
    return Episode(strategie="t", coin=coin, sens=1, notional_usd=notional,
                   prix_entree=100.0, prix_sortie=101.0, ts_open_ms=ts)


# ═══════════════ causalité ═══════════════
def test_un_carnet_posterieur_nest_jamais_choisi():
    """Un carnet 1 ms APRÈS l'épisode est plus proche — il est pourtant interdit."""
    idx = _index([(T0 - 60_000, 500.0), (T0 + 1, 999_999.0)])
    r = CAP.carnet_causal(idx, "BTC", T0)
    assert r["statut"] == "OK" and r["taille_usd"] == 500.0     # l'antérieur, pas le plus proche
    assert r["carnet_ts_ms"] == T0 - 60_000


def test_le_dernier_carnet_anterieur_gagne():
    idx = _index([(T0 - 200_000, 100.0), (T0 - 1_000, 700.0)])
    assert CAP.carnet_causal(idx, "BTC", T0)["taille_usd"] == 700.0


def test_carnet_a_lexact_instant_est_accepte():
    idx = _index([(T0, 800.0)])
    r = CAP.carnet_causal(idx, "BTC", T0)
    assert r["statut"] == "OK" and r["age_ms"] == 0.0


# ═══════════════ refus explicites ═══════════════
def test_aucun_carnet_anterieur_donne_sans_carnet_causal():
    idx = _index([(T0 + 5_000, 900.0)])
    r = CAP.carnet_causal(idx, "BTC", T0)
    assert r["statut"] == "SANS_CARNET_CAUSAL" and r["taille_usd"] is None


def test_carnet_trop_vieux_est_perime_pas_approche():
    idx = _index([(T0 - 10_000_000, 900.0)])
    r = CAP.carnet_causal(idx, "BTC", T0, age_max_ms=300_000)
    assert r["statut"] == "CARNET_PERIME" and r["taille_usd"] is None


def test_coin_absent_de_lindex():
    assert CAP.carnet_causal(_index([(T0, 1.0)]), "ETH", T0)["statut"] == "SANS_CARNET_CAUSAL"


def test_episode_sans_horodatage_nest_pas_joint():
    r = CAP.capacite_episode(_episode(ts=None), _index([(T0, 500.0)]))
    assert r["statut"] == "HORODATAGE_EPISODE_ABSENT" and r["capacite_usd"] is None


# ═══════════════ fill ratio ═══════════════
def test_fill_ratio_borne_a_un():
    r = CAP.capacite_episode(_episode(notional=100.0), _index([(T0, 5_000.0)]))
    assert r["capacite_usd"] == 5_000.0 and r["fill_ratio"] == 1.0


def test_capacite_insuffisante_donne_un_ratio_partiel():
    r = CAP.capacite_episode(_episode(notional=1_000.0), _index([(T0, 250.0)]))
    assert r["fill_ratio"] == 0.25


def test_sans_capacite_le_ratio_reste_none():
    r = CAP.capacite_episode(_episode(), _index([(T0 + 1, 500.0)]))
    assert r["capacite_usd"] is None and r["fill_ratio"] is None


# ═══════════════ agrégat ═══════════════
def test_agregat_nomme_ce_qui_na_pas_pu_etre_joint():
    idx = _index([(T0 - 1_000, 400.0)])
    episodes = [_episode(ts=T0, notional=1_000.0),
                _episode(ts=T0 - 10_000_000, notional=1_000.0),      # avant tout carnet
                _episode(ts=T0, notional=1_000.0, coin="DOGE")]      # coin absent
    r = CAP.enrichir_episodes(episodes, idx)
    assert r["n_episodes"] == 3 and r["n_avec_carnet_causal"] == 1
    assert r["couverture"] == round(1 / 3, 4)
    assert r["motifs_non_joints"]["SANS_CARNET_CAUSAL"] == 2
    assert r["capacite_mediane_usd"] == 400.0 and r["fill_ratio_median"] == 0.4
    assert r["qualite"] == "TOP_OF_BOOK_ONLY"


# ═══════════════ lecture disque ═══════════════
def test_chargement_ignore_les_lignes_illisibles_et_sans_taille(tmp_path):
    f = tmp_path / "carnet.jsonl"
    f.write_text(
        json.dumps({"coin": "BTC", "taille_min_usd": 300.0, "collecte_ts": 1_700_000_000.0}) + "\n"
        + json.dumps({"coin": "BTC", "collecte_ts": 1_700_000_001.0}) + "\n"     # sans taille
        + json.dumps({"coin": "BTC", "taille_min_usd": 0.0, "collecte_ts": 1_700_000_002.0}) + "\n"
        + "PAS DU JSON\n", encoding="utf-8")
    idx = CAP.charger_carnets(f)
    assert list(idx) == ["BTC"] and len(idx["BTC"]["ts"]) == 1
    assert idx["BTC"]["ts"][0] == 1_700_000_000_000        # secondes -> millisecondes


def test_fichier_absent_rend_un_index_vide(tmp_path):
    assert CAP.charger_carnets(tmp_path / "rien.jsonl") == {}


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "ops" / "episode_capacity.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans episode_capacity: %s" % interdit
