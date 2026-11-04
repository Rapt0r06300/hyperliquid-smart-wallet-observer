"""ALPHA — population wallets à l'échelle : archétype, indépendance d'entité, classement streaming."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import wallet_population as P  # noqa: E402

JOUR = 86_400_000


def test_archetype_scalper_et_momentum():
    scalper = [{"coin": "BTC", "ts_ms": i * 1000} for i in range(100)]     # 100 fills en ~100s
    assert P.archetype(scalper) == "scalper"
    mono = [{"coin": "PUMP", "ts_ms": d * JOUR} for d in range(10)]        # 1 coin, lent
    assert P.archetype(mono) == "momentum_mono_coin"


def test_independance_entite_detecte_cotrade():
    par_wallet = {
        "0xA": [{"coin": "BTC", "ts_ms": 1000}],
        "0xB": [{"coin": "BTC", "ts_ms": 1500}],    # même coin, +500ms de 0xA -> même entité
        "0xC": [{"coin": "ETH", "ts_ms": 9_000_000}],
    }
    clusters = P.independance_entite(par_wallet, fenetre_ms=2000)
    lie = {w for grp in clusters.values() for w in grp}
    assert "0xA" in lie and "0xB" in lie and "0xC" not in lie


def test_fix15_fingerprint_lie_les_wallets_sans_cotrade():
    # 2 wallets memes coins, tailles/cadences ~ identiques, mais JAMAIS au meme instant (pas de co-trade timing).
    recs_a = [{"coin": "BTC", "ts_ms": d * JOUR, "sz": 10.0} for d in range(6)]
    recs_b = [{"coin": "BTC", "ts_ms": d * JOUR + 100_000, "sz": 10.5} for d in range(6)]  # +100s -> pas co-trade
    assert P.fingerprints_similaires(P.fingerprint_wallet(recs_a), P.fingerprint_wallet(recs_b)) is True
    # co-trade seul ne les lie pas ; l'empreinte oui
    assert not P.independance_entite({"0xA": recs_a, "0xB": recs_b}, fenetre_ms=2000)
    clusters = P.clusters_entite({"0xA": recs_a, "0xB": recs_b}, fenetre_ms=2000)
    lie = {w for grp in clusters.values() for w in grp}
    assert "0xA" in lie and "0xB" in lie


def test_fix15_coins_differents_ne_lient_pas():
    fa = P.fingerprint_wallet([{"coin": "BTC", "ts_ms": 0, "sz": 10.0},
                               {"coin": "BTC", "ts_ms": JOUR, "sz": 10.0}])
    fb = P.fingerprint_wallet([{"coin": "DOGE", "ts_ms": 0, "sz": 10.0},
                               {"coin": "DOGE", "ts_ms": JOUR, "sz": 10.0}])
    assert P.fingerprints_similaires(fa, fb) is False        # coins disjoints -> pas la meme entite


def test_classer_population_streaming(tmp_path):
    recs = []
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append({"adresse": "0xWIN", "coin": coin, "side": "LONG",
                         "ts_ms": (10 + d) * JOUR, "mid_at_fill": 100.0, "mid_forward": 100.3})
            recs.append({"adresse": "0xLOSE", "coin": coin, "side": "LONG",
                         "ts_ms": (10 + d) * JOUR, "mid_at_fill": 100.0, "mid_forward": 99.9})
    p = tmp_path / "pop.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    out = P.classer_population(str(p), min_fills=5)
    assert out["n_wallets"] == 2 and out["n_evalues"] == 2
    assert out["classement"][0]["wallet"] == "0xWIN"
    assert "archetype" in out["classement"][0] and "entite_potentiellement_liee" in out["classement"][0]


def test_bootstrap_population_vault_regime_ne_compte_pas_les_fragments_comme_vaults():
    rows = [
        {"vault_id": "A", "regime_id": "calm", "net_usd": 1.0},
        {"vault_id": "A", "regime_id": "calm", "net_usd": 3.0},
        {"vault_id": "A", "regime_id": "volatile", "net_usd": 2.0},
        {"vault_id": "B", "regime_id": "calm", "net_usd": 2.0},
        {"vault_id": "B", "regime_id": "volatile", "net_usd": 4.0},
        {"vault_id": "C", "regime_id": "calm", "net_usd": 3.0},
        {"vault_id": "C", "regime_id": "volatile", "net_usd": 5.0},
    ]
    out = P.bootstrap_population_by_vault_regime(rows, n_bootstrap=200, seed=11)
    assert out["status"] == "PROVEN"
    assert out["n_vaults"] == 3
    assert out["n_vault_regime_cells"] == 6
    assert out["n_observations"] == len(rows)
    assert out["vault_means"]["A"] == 2.0
    assert out["bootstrap_ci_low"] <= out["observed_mean"] <= out["bootstrap_ci_high"]


def test_bootstrap_population_vault_regime_refuse_donnees_incompletes():
    out = P.bootstrap_population_by_vault_regime(
        [{"vault_id": "A", "regime_id": "calm", "net_usd": 1.0}],
        min_vaults=2,
    )
    assert out["status"] == "UNMEASURABLE"
    assert out["reason"] == "vaults_insuffisants"
