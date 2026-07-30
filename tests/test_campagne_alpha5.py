"""Étape 3/3 — campagne ALPHA-5 sur tape réelle.

Ce que ces tests verrouillent : la campagne déclare TOUS ses essais au registre **avant** de lire un
résultat, elle ne peut jamais promouvoir, et elle nomme explicitement les familles qu'une tape BBO seule ne
permet pas de mesurer — au lieu de les faire disparaître du décompte.

Les tapes de test sont synthétiques : plomberie uniquement (IDEA-80), aucun chiffre n'en sort comme mesure.

Paper/SHADOW : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import cross_venue_conditions as CVC  # noqa: E402
from hl_observer.experimental import registre_essais  # noqa: E402
from hl_observer.ops import campagne_alpha5 as CAMP  # noqa: E402

T0 = 1_700_000_000_000


def _ligne(coin, ts, bin_px, hl_px, ecart=0.01):
    return json.dumps({"coin": coin, "ts_ms": ts,
                       "bin_bid": bin_px, "bin_ask": bin_px + ecart,
                       "hl_bid": hl_px, "hl_ask": hl_px + ecart})


def _ecrire_tape(root: Path, coin="BTC", n=400, choc_tous=20) -> Path:
    """Tape avec des sauts periodiques du mid Binance, pour declencher des PRICE_SHOCK."""
    src = root / CAMP.SOURCE_RELPATH
    src.parent.mkdir(parents=True, exist_ok=True)
    lignes = []
    px = 100.0
    for i in range(n):
        if i % choc_tous == 0 and i:
            px *= 1.003 if (i // choc_tous) % 2 else 0.997      # ~30 bps : au-dessus du seuil 8 bps
        lignes.append(_ligne(coin, T0 + i * 200, round(px, 6), round(px, 6)))
    src.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return src


# ═══════════════ chargement ═══════════════
def test_chargement_filtre_le_coin_et_ignore_les_lignes_cassees(tmp_path):
    src = tmp_path / "tape.jsonl"
    src.write_text(
        _ligne("BTC", T0, 100.0, 100.0) + "\n"
        + _ligne("ETH", T0, 50.0, 50.0) + "\n"
        + "PAS DU JSON\n"
        + json.dumps({"coin": "BTC", "ts_ms": T0 + 1, "bin_bid": 0.0, "bin_ask": 1.0,
                      "hl_bid": 1.0, "hl_ask": 2.0}) + "\n",       # bid nul -> rejete
        encoding="utf-8")
    t = CAMP.charger_tape(src, "BTC")
    assert len(t["hl_bbo"]) == 1 and len(t["binance_bt"]) == 1


def test_carnet_croise_localement_est_rejete(tmp_path):
    src = tmp_path / "tape.jsonl"
    src.write_text(json.dumps({"coin": "BTC", "ts_ms": T0, "bin_bid": 101.0, "bin_ask": 100.0,
                               "hl_bid": 100.0, "hl_ask": 100.1}) + "\n", encoding="utf-8")
    assert CAMP.charger_tape(src, "BTC")["hl_bbo"] == []


def test_fichier_absent_rend_une_tape_vide(tmp_path):
    assert CAMP.charger_tape(tmp_path / "rien.jsonl", "BTC")["n_lignes"] == 0


# ═══════════════ refus de conclure ═══════════════
def test_donnees_insuffisantes_ne_produisent_aucun_essai(tmp_path):
    _ecrire_tape(tmp_path, n=10)
    r = CAMP.executer(tmp_path, coin="BTC")
    assert r["statut"] == "DONNEES_INSUFFISANTES" and "n_essais" not in r
    assert r["promotion_possible"] is False


def test_les_familles_non_mesurables_sont_nommees_pas_effacees(tmp_path):
    _ecrire_tape(tmp_path)
    r = CAMP.executer(tmp_path, coin="BTC")
    assert set(r["familles_non_mesurables"]) == {"AGG_IMBALANCE", "TAKER_BURST"}
    assert r["familles_mesurables"] == ["PRICE_SHOCK"]
    assert "aggTrades" in r["limite_donnees"]


# ═══════════════ registre : tout est compté ═══════════════
def test_le_plan_est_preenregistre_avant_tout_resultat(tmp_path):
    _ecrire_tape(tmp_path)
    r = CAMP.executer(tmp_path, coin="BTC")
    assert r["statut"] == "EXECUTEE"
    lignes = registre_essais.charger(tmp_path)
    prereg = [x for x in lignes if x["phase"] == "preregistration"]
    resultats = [x for x in lignes if x["phase"] == "resultat"]
    assert len(prereg) == r["n_essais"] == len(resultats)
    # la pre-registration precede physiquement les resultats dans le journal append-only
    assert lignes.index(prereg[-1]) < lignes.index(resultats[0])


def test_les_essais_kill_restent_dans_la_population(tmp_path):
    _ecrire_tape(tmp_path)
    CAMP.executer(tmp_path, coin="BTC")
    lignes = registre_essais.charger(tmp_path)
    resultats = [x for x in lignes if x["phase"] == "resultat"]
    assert resultats and all(x["pass_kill"] in {"PASS", "KILL"} for x in resultats)
    assert any(x["pass_kill"] == "KILL" for x in resultats)      # les perdants ne disparaissent pas


def test_chaque_condition_x_horizon_est_un_essai(tmp_path):
    _ecrire_tape(tmp_path)
    r = CAMP.executer(tmp_path, coin="BTC", horizons=(500, 1000))
    assert r["n_essais"] == len(CVC.CONDITIONS) * 2
    assert len(r["verdicts"]) == r["n_essais"]


# ═══════════════ aucune promotion ═══════════════
def test_la_campagne_ne_promeut_jamais(tmp_path):
    _ecrire_tape(tmp_path)
    r = CAMP.executer(tmp_path, coin="BTC")
    assert r["shadow"] is True and r["promotion_possible"] is False and r["real_execution"] is False
    for v in r["verdicts"].values():
        assert v["statut"] in {"DISCOVERY_PROBE", "SHADOW_KILL", "SHADOW_DONNEES_INSUFFISANTES"}


def test_les_parametres_sont_preenregistres_dans_le_rapport(tmp_path):
    _ecrire_tape(tmp_path)
    r = CAMP.executer(tmp_path, coin="BTC")
    assert r["params_preenregistres"]["seuil_bps"] == 8.0        # figé dans le module, pas ajusté
    assert r["params_preenregistres"]["latence_ms"] == 400.0


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "ops" / "campagne_alpha5.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans campagne_alpha5: %s" % interdit
