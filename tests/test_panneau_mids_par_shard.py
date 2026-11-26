"""Panneau de mids assemblé depuis un cache PAR SHARD (25/11/2026) : IDENTIQUE au panneau construit à l'ancienne.

188 s mesurées à chaque nouveau shard ``allmids`` (tout relu en JSON). Le panneau assemblé doit rendre exactement
``_construire_panneau`` : mêmes instants, mêmes colonnes dans le même ordre, mêmes prix au bit près, mêmes cases
vides. Les données tirées au hasard couvrent les doublons d'horodatage dans un shard et entre shards (le premier lu
gagne), les horodatages invalides, les marchés '#'/'@', les prix illisibles ou non positifs, des shards qui se
chevauchent dans le temps et des coins qui apparaissent dans des ordres différents.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (RACINE / "src", RACINE / "tools"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

import etude_copiabilite as E  # noqa: E402

DEBUT = 1_795_000_000_000


def _shard(dossier: Path, nom: str, lignes: list[str]) -> dict:
    p = dossier / f"{nom}.jsonl.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress("".join(lignes).encode("utf-8")))
    return {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "shard": nom}


def _valeur(rng):
    choix = rng.random()
    if choix < 0.6:
        return str(round(float(rng.uniform(0.001, 90_000)), 6))
    if choix < 0.8:
        return float(rng.uniform(0.001, 90_000))
    return ["0", "-3", "abc", None, True, "nan", "1e400", 0, 7][int(rng.integers(0, 9))]


def _monde(dossier: Path, graine: int) -> list[dict]:
    rng = np.random.default_rng(graine)
    coins = ["BTC", "ETH", "SOL", "kPEPE", "#123", "@45", "HYPE", "xyz:TSLA", "DOGE"]
    shards = []
    for s in range(int(rng.integers(2, 7))):
        lignes = []
        for _ in range(int(rng.integers(5, 120))):
            choix = rng.random()
            if choix < 0.03:
                lignes.append("{casse\n")
                continue
            ts = DEBUT + int(rng.integers(0, 400)) * 1000                    # doublons dans et entre shards
            if choix < 0.08:
                ts = [None, float(ts), True, 0, -5, str(ts)][int(rng.integers(0, 6))]
            choisis = list(rng.choice(coins, size=int(rng.integers(0, len(coins))), replace=False))
            mids = {c: _valeur(rng) for c in choisis}
            ligne = {"ts_ms": ts, "mids": mids if rng.random() > 0.03 else ["pas", "un", "dict"]}
            lignes.append(json.dumps(ligne) + "\n")
        shards.append(_shard(dossier / "allmids", f"s{s}", lignes))
    return shards


def _identiques(a, b) -> None:
    assert a.ts.dtype == b.ts.dtype and np.array_equal(a.ts, b.ts)
    assert a.coins == b.coins
    assert a.px.shape == b.px.shape and a.px.dtype == b.px.dtype
    assert np.array_equal(a.px.view(np.uint64), b.px.view(np.uint64))             # au bit près, NaN compris
    assert (a.provenance, a.stale_ms) == (b.provenance, b.stale_ms)


@pytest.mark.parametrize("graine", range(12))
def test_le_panneau_assemble_est_identique_au_panneau_d_origine(graine, tmp_path):
    shards = _monde(tmp_path, graine)
    attendu = E._construire_panneau(shards, 120_000)
    for workers in (1, 2):
        cache = tmp_path / f"cache{workers}"
        _identiques(E._construire_panneau_par_shard(shards, 120_000, cache, workers=workers), attendu)
        _identiques(E._construire_panneau_par_shard(shards, 120_000, cache, workers=workers), attendu)  # cache chaud


def test_un_shard_de_plus_ne_relit_que_lui(tmp_path, monkeypatch):
    shards = _monde(tmp_path, 7)
    E._construire_panneau_par_shard(shards[:-1], 120_000, tmp_path / "cache", workers=1)
    lus = []
    vraie = E._mids_d_un_shard
    monkeypatch.setattr(E, "_mids_d_un_shard", lambda job: (lus.append(Path(job[0]).name), vraie(job))[1])
    _identiques(E._construire_panneau_par_shard(shards, 120_000, tmp_path / "cache", workers=1),
                E._construire_panneau(shards, 120_000))
    assert lus == [Path(shards[-1]["path"]).name]


def test_l_ordre_des_shards_decide_du_doublon_comme_a_l_origine(tmp_path):
    a = _shard(tmp_path, "a", [json.dumps({"ts_ms": DEBUT, "mids": {"BTC": "1", "ETH": "2"}}) + "\n"])
    b = _shard(tmp_path, "b", [json.dumps({"ts_ms": DEBUT, "mids": {"SOL": "3", "BTC": "9"}}) + "\n",
                               json.dumps({"ts_ms": DEBUT - 1, "mids": {"SOL": "4"}}) + "\n"])
    for ordre in ([a, b], [b, a]):
        _identiques(E._construire_panneau_par_shard(ordre, 120_000, tmp_path / "cache", workers=1),
                    E._construire_panneau(ordre, 120_000))
    panneau = E._construire_panneau_par_shard([a, b], 120_000, tmp_path / "cache", workers=1)
    assert panneau.coins == ("SOL", "BTC", "ETH") and panneau.px[1].tolist()[1] == 1.0     # a gagne en DEBUT


def test_un_instant_hors_int64_rend_la_main_a_l_ancienne_construction(tmp_path):
    s = _shard(tmp_path, "g", [json.dumps({"ts_ms": 2 ** 64, "mids": {"BTC": "1"}}) + "\n"])
    assert E._construire_panneau_par_shard([s], 120_000, tmp_path / "cache", workers=1) is None


def test_load_mid_panel_passe_par_le_cache_par_shard(tmp_path, monkeypatch):
    shards = _monde(tmp_path, 3)
    appels = []
    vraie = E._construire_panneau_par_shard
    monkeypatch.setattr(E, "_construire_panneau_par_shard", lambda *a, **k: (appels.append(1), vraie(*a, **k))[1])
    _identiques(E.load_mid_panel(shards, 120_000, cache_dir=tmp_path / "cache"),
                E._construire_panneau(shards, 120_000))
    assert appels == [1]
