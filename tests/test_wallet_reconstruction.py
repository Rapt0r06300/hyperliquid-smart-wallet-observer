"""Global Wallet Observer — reconstruction du cycle de vie depuis les fills L1.

Le test décisif est `test_un_start_pos_divergent_marque_desync_au_lieu_de_mentir` : quand l'exchange dit que
la position valait 5 et que notre accumulateur dit 3, il MANQUE des fills. Produire quand même un
OPEN/ADD/CLOSE d'apparence normale serait se tromper sans le savoir. On marque `DESYNC`.

Paper only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.following import wallet_reconstruction as WR  # noqa: E402

W = "0xabc"
T0 = 1_700_000_000_000


def _fill(i, side, sz, px=100.0, coin="BTC", wallet=W, start_pos=None, **kw):
    f = {"user": wallet, "coin": coin, "side": side, "sz": sz, "px": px,
         "time": T0 + i * 1_000, "tid": "t%d" % i, "oid": 1000 + i}
    if start_pos is not None:
        f["start_pos"] = start_pos
    f.update(kw)
    return f


# ═══════════════ cycle de vie ═══════════════
def test_open_add_reduce_close():
    fills = [_fill(0, "B", 1.0, start_pos=0.0), _fill(1, "B", 1.0, start_pos=1.0),
             _fill(2, "A", 0.5, start_pos=2.0), _fill(3, "A", 1.5, start_pos=1.5)]
    r = WR.reconstruire(fills)
    assert [e["action"] for e in r.episodes] == ["OPEN", "ADD", "REDUCE", "CLOSE"]
    assert r.resume()["n_desyncs"] == 0 and r.resume()["fiable"] is True
    assert r.positions[(W, "BTC")].quantite == 0.0


def test_flip_est_distingue_dun_close_suivi_dun_open():
    """Vendre 3 depuis +1 traverse zéro : c'est un FLIP, pas un CLOSE."""
    fills = [_fill(0, "B", 1.0, start_pos=0.0), _fill(1, "A", 3.0, start_pos=1.0)]
    r = WR.reconstruire(fills)
    assert [e["action"] for e in r.episodes] == ["OPEN", "FLIP"]
    assert r.episodes[1]["position_apres"] == -2.0


def test_short_puis_rachat_complet():
    fills = [_fill(0, "A", 2.0, start_pos=0.0), _fill(1, "B", 2.0, start_pos=-2.0)]
    r = WR.reconstruire(fills)
    assert [e["action"] for e in r.episodes] == ["OPEN", "CLOSE"]
    assert r.episodes[0]["position_apres"] == -2.0


def test_prix_moyen_pondere_sur_un_add():
    fills = [_fill(0, "B", 1.0, px=100.0, start_pos=0.0), _fill(1, "B", 1.0, px=110.0, start_pos=1.0)]
    r = WR.reconstruire(fills)
    assert r.episodes[1]["prix_moyen_apres"] == 105.0


def test_un_reduce_ne_change_pas_le_prix_moyen():
    fills = [_fill(0, "B", 2.0, px=100.0, start_pos=0.0), _fill(1, "A", 1.0, px=130.0, start_pos=2.0)]
    r = WR.reconstruire(fills)
    assert r.episodes[1]["prix_moyen_apres"] == 100.0


# ═══════════════ le test décisif : désynchronisation ═══════════════
def test_un_start_pos_divergent_marque_desync_au_lieu_de_mentir():
    fills = [_fill(0, "B", 1.0, start_pos=0.0), _fill(1, "A", 1.0, start_pos=5.0)]   # il manque des fills
    r = WR.reconstruire(fills)
    resume = r.resume()
    assert resume["n_desyncs"] == 1 and resume["fiable"] is False
    assert "manquent" in resume["note_desync"]
    assert r.episodes[1]["desync"] is True
    # `start_pos` fait autorité : la position d'arrivee suit l'exchange, pas notre accumulateur
    assert r.episodes[1]["position_apres"] == 4.0


def test_sans_start_pos_laccumulateur_prend_le_relais():
    fills = [_fill(0, "B", 1.0), _fill(1, "B", 1.0), _fill(2, "A", 2.0)]
    r = WR.reconstruire(fills)
    assert [e["action"] for e in r.episodes] == ["OPEN", "ADD", "CLOSE"]
    assert all(e["source_start_pos"] is False for e in r.episodes)
    assert r.resume()["n_desyncs"] == 0


def test_on_peut_ignorer_start_pos_explicitement():
    fills = [_fill(0, "B", 1.0, start_pos=0.0), _fill(1, "A", 1.0, start_pos=5.0)]
    r = WR.reconstruire(fills, utiliser_start_pos=False)
    assert r.resume()["n_desyncs"] == 0 and r.episodes[1]["position_apres"] == 0.0


# ═══════════════ deny-by-default ═══════════════
def test_les_fills_illisibles_sont_comptes_pas_ignores():
    # `oid` distincts : sans identite propre, deux fills malformes partageraient la meme cle de dedup
    # et l'un serait compte comme doublon plutot que comme refus (piege verifie a l'ecriture du test).
    fills = [_fill(0, "B", 1.0),
             {"user": W, "coin": "BTC", "side": "B", "px": 100.0, "time": T0, "oid": 91},
             {"user": W, "coin": "BTC", "side": "B", "sz": 1.0, "time": T0, "oid": 92},
             {"user": W, "coin": "BTC", "side": "?", "sz": 1.0, "px": 100.0, "time": T0, "oid": 93},
             {"coin": "BTC", "side": "B", "sz": 1.0, "px": 100.0, "time": T0, "oid": 94},
             {"user": W, "coin": "BTC", "side": "B", "sz": 1.0, "px": 100.0, "oid": 95}]
    r = WR.reconstruire(fills)
    refus = r.resume()["refus"]
    assert refus["TAILLE_ABSENTE"] == 1 and refus["PRIX_ABSENT"] == 1
    assert refus["SENS_INCONNU"] == 1 and refus["WALLET_OU_COIN_ABSENT"] == 1
    assert refus["HORODATAGE_ABSENT"] == 1
    assert len(r.episodes) == 1


def test_une_taille_nulle_nest_pas_un_fill():
    r = WR.reconstruire([_fill(0, "B", 0.0)])
    assert r.episodes == [] and r.resume()["refus"]["TAILLE_ABSENTE"] == 1


# ═══════════════ dédup et ordre ═══════════════
def test_le_meme_tid_nest_compte_quune_fois():
    f = _fill(0, "B", 1.0)
    r = WR.reconstruire([f, dict(f)])
    assert len(r.episodes) == 1 and r.resume()["n_doublons"] == 1


def test_sans_tid_la_cle_retombe_sur_oid_temps_taille():
    a = {"user": W, "coin": "BTC", "side": "B", "sz": 1.0, "px": 100.0, "time": T0, "oid": 7}
    r = WR.reconstruire([a, dict(a)])
    assert len(r.episodes) == 1 and r.resume()["n_doublons"] == 1


def test_les_fills_sont_rejoues_dans_lordre_chronologique():
    fills = [_fill(2, "A", 1.0), _fill(0, "B", 1.0), _fill(1, "B", 1.0)]
    r = WR.reconstruire(fills)
    assert [e["ts_ms"] for e in r.episodes] == sorted(e["ts_ms"] for e in r.episodes)
    assert [e["action"] for e in r.episodes] == ["OPEN", "ADD", "REDUCE"]


# ═══════════════ TWAP et multi-wallet ═══════════════
def test_le_twap_id_est_conserve_et_compte():
    fills = [_fill(0, "B", 1.0, twap_id="tw1"), _fill(1, "B", 1.0, twapId="tw1"), _fill(2, "B", 1.0)]
    r = WR.reconstruire(fills)
    assert r.resume()["n_twap"] == 2
    assert r.episodes[0]["twap_id"] == "tw1" and r.episodes[2]["twap_id"] is None


def test_un_twap_id_nul_nest_pas_un_identifiant():
    r = WR.reconstruire([_fill(0, "B", 1.0, twap_id=0)])
    assert r.episodes[0]["twap_id"] is None


def test_les_wallets_et_coins_sont_isoles():
    fills = [_fill(0, "B", 1.0, wallet="0xa"), _fill(1, "B", 1.0, wallet="0xb"),
             _fill(2, "B", 1.0, wallet="0xa", coin="ETH")]
    r = WR.reconstruire(fills)
    assert all(e["action"] == "OPEN" for e in r.episodes)     # aucun ne contamine l'autre
    assert r.resume()["n_wallets"] == 2
    par_wallet = WR.episodes_par_wallet(r)
    assert set(par_wallet) == {"0xa", "0xb"} and len(par_wallet["0xa"]) == 2


def test_le_resume_compte_les_actions_et_les_positions_ouvertes():
    fills = [_fill(0, "B", 1.0), _fill(1, "B", 1.0, wallet="0xb")]
    resume = WR.reconstruire(fills).resume()
    assert resume["par_action"]["OPEN"] == 2 and resume["n_positions_ouvertes"] == 2
    assert resume["real_execution"] is False


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "following" / "wallet_reconstruction.py").read_text(
        encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans wallet_reconstruction: %s" % interdit
