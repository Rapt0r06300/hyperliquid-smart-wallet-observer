"""HISTORICAL_HOLDOUT_V1 — micro-échantillon AWS : plafonds + arrêt auto + GO/NO-GO, sur client S3 FACTICE.

Aucun réseau, aucune clé, aucun compte : on injecte un faux client S3. Prouve : plafonds durs (30 LIST, 6 GET,
50 Mo) qui LÈVENT, arrêt auto NO-GO (attribution vault nulle), et chemin GO (attribution + jointure L2 OK).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import lz4.frame
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("holdout_micro_download", _ROOT / "tools" / "holdout_micro_download.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

V = "0xvault1"
T0 = 1_700_000_000_000
D = "20260601"


def _book(mid, bsz=50.0):
    bid, ask = round(mid - 0.05, 3), round(mid + 0.05, 3)
    return [[{"px": str(bid), "sz": str(bsz)}, {"px": str(bid - 0.1), "sz": "50"}],
            [{"px": str(ask), "sz": str(bsz)}, {"px": str(ask + 0.1), "sz": "50"}]]


def _node_fills_lz4():
    lignes = []
    for i in range(5):
        t = T0 + i * 10_000
        lignes.append(json.dumps({"fills": [{"user": V, "coin": "SOL", "px": "100.0", "sz": "1", "side": "B",
                                             "time": t, "hash": "h%d" % i, "oid": i, "tid": i, "crossed": True}]}))
    return lz4.frame.compress("\n".join(lignes).encode("utf-8"))


def _l2_lz4(coin, mid_h):
    lignes = []
    for i in range(5):
        t = T0 + i * 10_000
        for tt, m, sz in ((t - 1000, 100.0, 40.0), (t, 100.0, 60.0), (t + 300_000, mid_h, 55.0)):
            lignes.append(json.dumps({"coin": coin, "time": tt, "levels": _book(m, sz)}))
    return lz4.frame.compress("\n".join(lignes).encode("utf-8"))


class _Body:
    def __init__(self, data): self.data, self.i = data, 0
    def read(self, n=-1):
        if self.i >= len(self.data):
            return b""
        j = self.i + (n if n and n > 0 else len(self.data))
        bloc = self.data[self.i:j]; self.i = j
        return bloc


class FakeS3:
    def __init__(self, listings, objets): self.listings, self.objets = listings, objets
    def list_objects_v2(self, Bucket, Prefix, Delimiter, MaxKeys, RequestPayer):
        return self.listings.get(Prefix, {"CommonPrefixes": [], "Contents": []})
    def get_object(self, Bucket, Key, RequestPayer):
        return {"Body": _Body(self.objets[Key])}
    def get_bucket_location(self, Bucket):
        return {"LocationConstraint": "us-east-1"}


def _fake_go():
    node_key = "node_fills_by_block/%s/12" % D
    objets = {node_key: _node_fills_lz4(),
              "market_data/%s/12/l2Book/SOL.lz4" % D: _l2_lz4("SOL", 100.5),
              "market_data/%s/12/l2Book/BTC.lz4" % D: _l2_lz4("BTC", 50000.0)}
    listings = {
        "node_fills_by_block/": {"CommonPrefixes": [{"Prefix": "node_fills_by_block/%s/" % D}], "Contents": []},
        "market_data/": {"CommonPrefixes": [{"Prefix": "market_data/%s/" % D}], "Contents": []},
        "node_fills_by_block/%s/" % D: {"CommonPrefixes": [], "Contents": [{"Key": node_key, "Size": len(objets[node_key])}]},
    }
    return FakeS3(listings, objets)


def test_plafonds_durs_levent():
    cli = M.ClientBorne(FakeS3({}, {"k": b"x" * (M.MAX_OCTETS + 1)}))
    cli.n_list = M.MAX_LIST
    with pytest.raises(M.ArretPlafond):
        cli.lister("b", "p")                                   # 30 LIST atteintes
    cli2 = M.ClientBorne(FakeS3({}, {"gros": b"x" * (M.MAX_OCTETS + 10)}))
    with pytest.raises(M.ArretPlafond):
        cli2.telecharger("b", "gros")                          # > 50 Mo pendant le GET
    cli3 = M.ClientBorne(FakeS3({}, {"k": b"ok"})); cli3.n_get = M.MAX_GET
    with pytest.raises(M.ArretPlafond):
        cli3.telecharger("b", "k")                             # 6 GET atteints


def test_go_attribution_et_jointure_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SORTIE", tmp_path)
    cli = M.ClientBorne(_fake_go())
    r = M.executer(cli, [V], coin="SOL")
    assert r["verdict"] == "GO"
    assert r["gate"]["couverture"]["l2_synchronise"] >= 1 and r["gate"]["vaults_avec_fills"] == [V]
    assert r["requetes"]["get"] <= M.MAX_GET and r["requetes"]["list"] <= M.MAX_LIST
    assert r["octets"] <= M.MAX_OCTETS and r["cout_eur_estime"] <= M.MAX_EUR
    assert (tmp_path / "holdout_micro_preregistration.json").exists()   # figé AVANT lecture
    assert (tmp_path / "holdout_micro_go_nogo.json").exists()
    assert json.loads((tmp_path / "holdout_micro_preregistration.json").read_text())["prereg_hash"]


def test_nogo_attribution_nulle(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SORTIE", tmp_path)
    fake = _fake_go()
    # node_fills sans AUCUN vault suivi -> attribution nulle -> NO-GO (aucune approximation)
    r = M.executer(M.ClientBorne(fake), ["0xabsent"], coin="SOL")
    assert r["verdict"] == "NO_GO" and r["raison"] == "ATTRIBUTION_VAULT_NULLE"
