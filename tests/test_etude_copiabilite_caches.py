"""Caches des études de copiabilité (24/11/2026) : plus rapides, résultats IDENTIQUES.

Mesuré sur le coffre réel : demi-spreads ~15 min et panneau de mids 4 min 33 PAR étude, refaits par 7 études sur 8.
Verrouille :
- les demi-spreads lus via le cache par shard sont égaux, au bit près, à la lecture directe ;
- un shard déjà lu n'est plus relu ; seul un shard nouveau l'est ;
- le panneau de mids relu du cache est égal au panneau reconstruit, et un autre ensemble de shards le reconstruit ;
- la vérification SHA-256 (parallèle) écarte toujours un shard modifié.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools", RACINE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import etude_copiabilite as E  # noqa: E402


def test_filtre_temporel_reutilise_le_dataframe_si_tout_est_dans_la_fenetre():
    frame = pd.DataFrame({"time": pd.Series([10, 20, 30], dtype="Int64")})
    mask = frame["time"].between(0, 30)
    assert E.filtrer_observations_entre_bornes(frame, mask) is frame


def test_filtre_temporel_exclut_fail_closed_les_timestamps_inconnus():
    frame = pd.DataFrame({"time": pd.Series([10, pd.NA, 30], dtype="Int64")})
    mask = (frame["time"] >= 0) & (frame["time"] <= 30)
    resultat = E.filtrer_observations_entre_bornes(frame, mask)
    assert resultat["time"].tolist() == [10, 30]


def _shard(dossier: Path, nom: str, lignes: list[dict]) -> dict:
    p = dossier / f"{nom}.jsonl.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as g:
        g.writelines(json.dumps(x) + "\n" for x in lignes)
    return {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "shard": nom}


def _cotations(graine: int, n: int = 400) -> list[dict]:
    rng = np.random.default_rng(graine)
    lignes = []
    for i in range(n):
        coin = ["BTC", "ETH", "SOL"][i % 3]
        mid = 100.0 + float(rng.normal())
        ecart = abs(float(rng.normal(0.02, 0.01))) + 1e-4
        lignes.append({"coin": coin, "bid": mid - ecart, "ask": mid + ecart, "venue": "HL", "ts_ms": i})
    lignes.append({"coin": "BTC", "bid": 1.0, "ask": 2.0, "venue": "BINANCE"})      # autre venue : ignorée
    lignes.append({"coin": "ETH", "bid": 2.0, "ask": 1.0})                           # croisée : ignorée
    return lignes


def test_le_cache_des_demi_spreads_rend_exactement_la_lecture_directe(tmp_path):
    shards = [_shard(tmp_path / "s", f"bbo_{k}", _cotations(k)) for k in range(4)]
    direct = E.load_half_spreads(shards)
    en_ligne = E.load_half_spreads(shards, cache_dir=tmp_path / "cache", workers=1)
    en_parallele = E.load_half_spreads(shards, cache_dir=tmp_path / "cache2", workers=2)
    assert direct and direct == en_ligne == en_parallele                             # égalité au bit près
    assert E.load_half_spreads(shards, cache_dir=tmp_path / "cache", workers=1) == direct   # relu du cache


def test_un_shard_deja_lu_n_est_plus_relu_seul_le_nouveau_l_est(tmp_path, monkeypatch):
    shards = [_shard(tmp_path / "s", f"bbo_{k}", _cotations(k)) for k in range(3)]
    E.load_half_spreads(shards, cache_dir=tmp_path / "cache", workers=1)
    lus: list[str] = []
    vraie = E._spreads_observes
    monkeypatch.setattr(E, "_spreads_observes", lambda path, s: (lus.append(Path(path).name), vraie(path, s))[1])
    nouveau = _shard(tmp_path / "s", "bbo_nouveau", _cotations(9))
    avec = E.load_half_spreads([*shards, nouveau], cache_dir=tmp_path / "cache", workers=1)
    assert lus == ["bbo_nouveau.jsonl.gz"]
    assert avec == E.load_half_spreads([*shards, nouveau])


def _mids(debut: int, n: int = 50) -> list[dict]:
    return [{"ts_ms": debut + i * 1000, "mids": {"BTC": str(100 + i), "ETH": str(10 + i), "@1": "5", "#2": "1"}}
            for i in range(n)]


def test_le_panneau_relu_du_cache_est_le_panneau_reconstruit(tmp_path, monkeypatch):
    shards = [_shard(tmp_path / "m", "allmids_a", _mids(1_000)), _shard(tmp_path / "m", "allmids_b", _mids(90_000))]
    frais = E.load_mid_panel(shards, 120_000)
    premier = E.load_mid_panel(shards, 120_000, cache_dir=tmp_path / "cache")
    monkeypatch.setattr(E, "_construire_panneau", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reconstruit")))
    relu = E.load_mid_panel(shards, 120_000, cache_dir=tmp_path / "cache")
    for p in (premier, relu):
        assert np.array_equal(p.ts, frais.ts) and np.array_equal(p.px, frais.px, equal_nan=True)
        assert p.coins == frais.coins and p.provenance == frais.provenance and p.stale_ms == frais.stale_ms
    monkeypatch.undo()
    autre = [*shards, _shard(tmp_path / "m", "allmids_c", _mids(500_000))]
    assert len(E.load_mid_panel(autre, 120_000, cache_dir=tmp_path / "cache").ts) == 150   # autre ensemble : refait


def test_la_verification_sha256_parallele_ecarte_toujours_un_shard_modifie(tmp_path):
    racine = tmp_path
    dossier = racine / "runtime" / "coffre_certifie" / "local" / "shards" / "bbo"
    bons = [_shard(dossier, f"lot__bbo_{k}", _cotations(k, 20)) for k in range(5)]
    index = [{"famille": "bbo", "shard": str(Path(b["path"]).relative_to(racine).as_posix()), "sha256": b["sha256"]}
             for b in bons]
    index[2]["sha256"] = "0" * 64                                                       # shard modifié
    (racine / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").write_text(
        json.dumps({"shards": index}), encoding="utf-8")
    choisis, ecartes = E.select_shards(racine, {"bbo": ""})
    assert len(choisis["bbo"]) == 4
    assert [e["reason"] for e in ecartes] == ["sha256_different_de_l_index"]
    assert ecartes[0]["shard"] == index[2]["shard"]


def _funding(dossier: Path, nom: str, lignes: list[dict]) -> dict:
    return _shard(dossier, nom, lignes)


def test_le_cache_du_funding_rend_exactement_les_memes_tuples(tmp_path):
    """25/11/2026 : 102 s de JSON (12,5 M lignes) refaites par 4 etudes. Memes tuples, memes types, meme ordre."""
    exact = [{"coin": "BTC", "ts_ms": 1_795_000_000_000 + i, "funding": 1e-5 * i} for i in range(50)]
    exact.append({"coin": "ETH", "ts_ms": 1_795_000_000_500, "funding": None})          # ignoree
    melange = [{"coin": "SOL", "ts_ms": 1_795_000_000_000, "funding": 0},                 # int : shard relu
               {"coin": "", "ts_ms": None, "funding": "0.0001"},                          # str et ts absent
               {"funding": 2e-6}]                                                         # coin absent
    shards = [_funding(tmp_path / "f", "asset_ctx_a", exact), _funding(tmp_path / "f", "asset_ctx_b", melange)]
    direct = list(E.load_funding(shards))
    for workers in (1, 2):
        cache = tmp_path / f"cache{workers}"
        premier = list(E.load_funding(shards, cache_dir=cache, workers=workers))
        relu = list(E.load_funding(shards, cache_dir=cache, workers=workers))
        assert premier == direct and relu == direct
        assert [tuple(map(type, x)) for x in relu] == [tuple(map(type, x)) for x in direct]


def test_le_funding_n_est_relu_que_pour_un_shard_marque_a_relire(tmp_path, monkeypatch):
    exact = [{"coin": "BTC", "ts_ms": 1_795_000_000_000 + i, "funding": 1e-5} for i in range(5)]
    melange = [{"coin": "SOL", "ts_ms": 1_795_000_000_000, "funding": 0}]
    shards = [_funding(tmp_path / "f", "a", exact), _funding(tmp_path / "f", "b", melange)]
    list(E.load_funding(shards, cache_dir=tmp_path / "cache", workers=1))
    lus: list[str] = []
    vraie = E._lire_funding
    monkeypatch.setattr(E, "_lire_funding", lambda path: (lus.append(Path(path).name), vraie(path))[1])
    list(E.load_funding(shards, cache_dir=tmp_path / "cache", workers=1))
    assert lus == ["b.jsonl.gz"]                                  # seul le shard non exact est relu
