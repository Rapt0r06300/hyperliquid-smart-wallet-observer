"""Preuve de scellement par identité (23/11/2026) : 100 % de couverture sans un seul doublon.

Verrouille :
- un fichier « à prouver » dont toutes les lignes sont au coffre devient SCELLE sans rien verser ;
- un fichier dont certaines lignes manquent : seules les absentes entrent, UNE fois, puis le fichier est SCELLE ;
- une preuve ne vaut que pour le contenu prouvé : un fichier modifié redevient « à prouver ».
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import prouver_scellement as P  # noqa: E402
from hl_observer.datasets import recensement_donnees as R  # noqa: E402

NOW = 1_795_000_000_000


def _ligne(i: int) -> dict:
    return {"coin": "ETH", "ts_ms": NOW - 100_000 + i, "mark": 2000.0 + i}


def _session(root: Path, lignes: list[dict]) -> Path:
    p = root / "runtime/archive/session_20261109_100000/asset_ctx_tape.jsonl"       # avant la règle : à prouver
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(x) + "\n" for x in lignes), encoding="utf-8")
    return p


def _coffre(root: Path, lignes: list[dict]) -> None:
    rel = "runtime/coffre_certifie/local/shards/asset_ctx/lot__asset_ctx_tape.jsonl.gz"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as g:
        g.writelines(json.dumps({**x, "tier": "LOCAL"}) + "\n" for x in lignes)
    (root / P.INDEX).write_text(json.dumps({"shards": [{
        "famille": "asset_ctx", "shard": rel, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "deposes": len(lignes), "ts_min_ms": NOW - 200_000, "ts_max_ms": NOW, "coins": ["ETH"]}]}), encoding="utf-8")
    etat = root / R.ETAT_COFFRE
    etat.write_text(json.dumps({"runtime\\data\\asset_ctx_tape.jsonl": {
        "taille": 1, "prefixe_octets": 1, "prefixe_sha256": "x"}}), encoding="utf-8")


def _deposes(root: Path) -> list[dict]:
    out = []
    for s in json.loads((root / P.INDEX).read_text(encoding="utf-8"))["shards"]:
        with gzip.open(root / s["shard"], "rt", encoding="utf-8") as g:
            out += [json.loads(x) for x in g]
    return out


def test_un_fichier_entierement_au_coffre_est_prouve_sans_rien_verser(tmp_path):
    lignes = [_ligne(i) for i in range(30)]
    _session(tmp_path, lignes)
    _coffre(tmp_path, lignes)
    assert R.recenser(tmp_path)["totaux"].get("A_PROUVER", {}).get("fichiers") == 1
    assert P.main(["--racine", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert not list((tmp_path / P.HISTOIRE).glob("*.jsonl.gz"))
    r = R.recenser(tmp_path)
    assert "A_PROUVER" not in r["totaux"] and r["cent_pour_cent"]
    assert len(_deposes(tmp_path)) == 30


def test_seules_les_lignes_absentes_entrent_une_fois_puis_le_fichier_est_scelle(tmp_path):
    lignes = [_ligne(i) for i in range(30)]
    _session(tmp_path, lignes)
    _coffre(tmp_path, lignes[:20])                                          # 10 lignes jamais scellées
    assert P.main(["--racine", str(tmp_path), "--now-ms", str(NOW)]) == 0
    deposes = _deposes(tmp_path)
    assert sorted(x["ts_ms"] for x in deposes) == sorted(x["ts_ms"] for x in lignes)   # 30, aucune en double
    assert sum(1 for x in deposes if x.get("prouve_absent_du_coffre")) == 10
    assert R.recenser(tmp_path)["cent_pour_cent"]
    assert P.main(["--racine", str(tmp_path), "--now-ms", str(NOW)]) == 0          # rien de plus au 2e passage
    assert len(_deposes(tmp_path)) == 30


def test_une_preuve_ne_vaut_que_pour_le_contenu_prouve(tmp_path):
    lignes = [_ligne(i) for i in range(30)]
    session = _session(tmp_path, lignes)
    _coffre(tmp_path, lignes)
    assert P.main(["--racine", str(tmp_path), "--now-ms", str(NOW)]) == 0
    with session.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_ligne(99)) + "\n")
    st = session.stat()
    os.utime(session, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    r = R.recenser(tmp_path)
    assert r["totaux"].get("A_PROUVER", {}).get("fichiers") == 1
    assert r["listes"]["A_PROUVER"][0]["detail"].startswith("preuve périmée")
