"""Pipeline Global Wallet Observer, bout en bout.

Ce qui est verrouillé ici : une source non autoritative n'entre jamais dans le dataset de scoring, un wallet
en DESYNC n'est jamais scoré, et un coin sans bande de prix ne produit pas un markout de 0.

Paper/read-only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import global_observer_pipeline as GOP  # noqa: E402

T0 = 1_700_000_000_000


def _ecrire(p: Path, lignes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(x) for x in lignes) + "\n", encoding="utf-8")
    return p


def _fills_vault(tmp_path, n=30, wallet="0xaaa", coin="BTC", avec_start_pos=True):
    lignes = []
    pos = 0.0
    for i in range(n):
        signe = 1 if i % 2 == 0 else -1
        ligne = {"vault": wallet, "coin": coin, "px": 100.0 + i, "sz": 1.0,
                 "ts_ms": T0 + i * 10_000, "signe": signe, "oid": 1000 + i}
        if avec_start_pos:
            ligne["start_position"] = pos
        pos += signe * 1.0
        lignes.append(ligne)
    return _ecrire(tmp_path / "runtime" / "data" / "vault_fills.jsonl", lignes)


def _prix_large(tmp_path, coins=("BTC",), n=400, pas_ms=1_000):
    """Bande allMids format LARGE : {"ts_ms":..., "mids": {coin: px}}."""
    lignes = [{"ts_ms": T0 + i * pas_ms, "mids": {c: 100.0 + i * 0.01 for c in coins}} for i in range(n)]
    return _ecrire(tmp_path / "runtime" / "data" / "prix.jsonl", lignes)


# ═══════════════ chargement des prix : deux formats ═══════════════
def test_le_format_large_allmids_est_lu(tmp_path):
    p = _prix_large(tmp_path, coins=("BTC", "ETH"), n=5)
    idx = GOP.charger_prix(p)
    assert set(idx) == {"BTC", "ETH"} and len(idx["BTC"]["ts"]) == 5


def test_le_format_long_est_lu_et_les_secondes_converties(tmp_path):
    p = _ecrire(tmp_path / "l.jsonl", [{"coin": "BTC", "ts": 1_700_000_000.0, "mid": 50.0}])
    idx = GOP.charger_prix(p)
    assert idx["BTC"]["ts"][0] == T0                      # secondes -> millisecondes


def test_les_indices_internes_ne_sont_pas_des_coins(tmp_path):
    p = _ecrire(tmp_path / "l.jsonl", [{"ts_ms": T0, "mids": {"#5090": 0.5, "@107": 57.0, "BTC": 100.0}}])
    assert set(GOP.charger_prix(p)) == {"BTC"}


def test_le_filtre_coins_borne_la_memoire(tmp_path):
    p = _prix_large(tmp_path, coins=("BTC", "ETH", "SOL"), n=3)
    assert set(GOP.charger_prix(p, coins={"BTC"})) == {"BTC"}


# ═══════════════ markout causal ═══════════════
def test_le_markout_suit_le_sens_du_wallet(tmp_path):
    idx = GOP.charger_prix(_prix_large(tmp_path, n=100))
    long_ = GOP.markout_bps(idx, coin="BTC", ts_ms=T0, sens=1, horizon_ms=10_000)
    short = GOP.markout_bps(idx, coin="BTC", ts_ms=T0, sens=-1, horizon_ms=10_000)
    assert long_ > 0 and short < 0 and long_ == -short      # prix monte : bon pour le long


def test_un_coin_sans_prix_na_pas_de_markout_et_nest_pas_zero(tmp_path):
    idx = GOP.charger_prix(_prix_large(tmp_path, coins=("BTC",), n=10))
    assert GOP.markout_bps(idx, coin="DOGE", ts_ms=T0, sens=1, horizon_ms=1_000) is None


def test_un_prix_hors_tolerance_ne_produit_pas_de_markout(tmp_path):
    idx = GOP.charger_prix(_prix_large(tmp_path, n=3, pas_ms=1_000))
    assert GOP.markout_bps(idx, coin="BTC", ts_ms=T0, sens=1, horizon_ms=10_000_000) is None


def test_un_sens_inconnu_ne_produit_pas_de_markout(tmp_path):
    idx = GOP.charger_prix(_prix_large(tmp_path, n=50))
    assert GOP.markout_bps(idx, coin="BTC", ts_ms=T0, sens=0, horizon_ms=1_000) is None


# ═══════════════ bout en bout ═══════════════
def test_le_pipeline_reconstruit_score_et_compose_la_shortlist(tmp_path):
    _fills_vault(tmp_path, n=60)
    _prix_large(tmp_path, n=1_000)
    r = GOP.executer(tmp_path, sources=(("runtime/data/vault_fills.jsonl", "vault_fills"),),
                     prix_relpath="runtime/data/prix.jsonl", horizon_markout_ms=5_000,
                     cout_ar_bps=0.0, min_episodes=5)
    assert r["statut"] == "EXECUTE"
    assert r["ingestion"]["n_fills"] == 60 and r["ingestion"]["n_refuses"] == 0
    assert r["wallets"]["vus"] == 1 and r["wallets"]["fiables"] == 1
    assert r["markouts"]["couverture"] > 0.5
    assert r["shortlist"]["slots_utilises"] <= r["shortlist"]["limite_hl"]
    assert r["paper_only"] is True and r["real_execution"] is False


def test_une_source_non_autoritative_nentre_pas_dans_le_scoring(tmp_path):
    _ecrire(tmp_path / "runtime" / "data" / "miroir.jsonl",
            [{"user": "0xbbb", "coin": "BTC", "px": 100.0, "sz": 1.0, "time": T0 + i, "side": "B"}
             for i in range(50)])
    r = GOP.executer(tmp_path, sources=(("runtime/data/miroir.jsonl", "miroir_non_verifie"),),
                     prix_relpath=None, min_episodes=2)
    assert r["statut"] == "AUCUN_FILL_AUTORITATIF"
    assert r["sources"][0]["autoritative"] is False


def test_un_wallet_en_desync_est_exclu_du_scoring(tmp_path):
    """`start_pos` incoherent => des fills manquent => le wallet ne peut pas etre score."""
    lignes = [{"vault": "0xccc", "coin": "BTC", "px": 100.0, "sz": 1.0, "ts_ms": T0, "signe": 1,
               "start_position": 0.0, "oid": 1},
              {"vault": "0xccc", "coin": "BTC", "px": 101.0, "sz": 1.0, "ts_ms": T0 + 1_000,
               "signe": -1, "start_position": 99.0, "oid": 2}]
    _ecrire(tmp_path / "runtime" / "data" / "vault_fills.jsonl", lignes)
    _prix_large(tmp_path, n=50)
    r = GOP.executer(tmp_path, sources=(("runtime/data/vault_fills.jsonl", "vault_fills"),),
                     prix_relpath="runtime/data/prix.jsonl", min_episodes=1)
    assert r["wallets"]["vus"] == 1 and r["wallets"]["en_desync"] == 1
    assert r["wallets"]["fiables"] == 0 and r["wallets"]["scorables"] == 0
    assert r["shortlist"]["core"] == []


def test_sans_bande_de_prix_aucun_wallet_nest_scorable(tmp_path):
    _fills_vault(tmp_path, n=40)
    r = GOP.executer(tmp_path, sources=(("runtime/data/vault_fills.jsonl", "vault_fills"),),
                     prix_relpath=None, min_episodes=5)
    assert r["wallets"]["fiables"] == 1 and r["wallets"]["scorables"] == 0
    assert r["markouts"]["n_episodes_avec_markout"] == 0      # aucun markout, donc aucun score


def test_un_edge_negatif_apres_couts_ne_donne_aucun_core(tmp_path):
    _fills_vault(tmp_path, n=60)
    _prix_large(tmp_path, n=1_000)
    r = GOP.executer(tmp_path, sources=(("runtime/data/vault_fills.jsonl", "vault_fills"),),
                     prix_relpath="runtime/data/prix.jsonl", cout_ar_bps=10_000.0, min_episodes=5)
    assert r["wallets"]["eligibles_core"] == 0 and r["shortlist"]["core"] == []


def test_source_absente_est_signalee_sans_planter(tmp_path):
    r = GOP.executer(tmp_path, sources=(("runtime/data/rien.jsonl", "vault_fills"),), prix_relpath=None)
    assert r["statut"] == "AUCUN_FILL_AUTORITATIF"
    assert r["sources"][0]["statut"] == "FICHIER_ABSENT"


def test_le_rapport_sécrit_sur_disque(tmp_path):
    _fills_vault(tmp_path, n=30)
    r = GOP.executer(tmp_path, sources=(("runtime/data/vault_fills.jsonl", "vault_fills"),),
                     prix_relpath=None, min_episodes=5)
    assert GOP.ecrire_rapport(r, tmp_path).exists()


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "ops" / "global_observer_pipeline.py").read_text(
        encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans global_observer_pipeline: %s" % interdit
