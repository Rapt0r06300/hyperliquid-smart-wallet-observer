"""[PORTABILITE item 3] Verrou du wheelhouse : versions + SHA-256 de chaque roue. Toute divergence
(roue modifiee, manquante, ajoutee) est detectee. Testable partout avec de fausses .whl. 0 reseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import wheelhouse_lock as W                                # noqa: E402


def _wheelhouse(tmp_path, roues):
    d = tmp_path / "wheelhouse"
    d.mkdir()
    for nom, contenu in roues.items():
        (d / nom).write_bytes(contenu)
    return d


def test_construit_verrou_nom_version_sha(tmp_path):
    d = _wheelhouse(tmp_path, {"numpy-1.26.4-cp311-cp311-win_amd64.whl": b"AAA",
                               "pandas-2.2.0-cp311-cp311-win_amd64.whl": b"BBBB"})
    v = W.construire_verrou(d)
    assert v["schema"] == W.SCHEMA and v["n"] == 2
    r = v["roues"]["numpy-1.26.4-cp311-cp311-win_amd64.whl"]
    assert r["dist"] == "numpy" and r["version"] == "1.26.4" and len(r["sha256"]) == 64 and r["taille"] == 3


def test_ecrire_puis_verifier_ok(tmp_path):
    d = _wheelhouse(tmp_path, {"httpx-0.27.0-py3-none-any.whl": b"ZZZ"})
    lock = tmp_path / "WHEELHOUSE_LOCK.json"
    W.ecrire_verrou(d, lock)
    res = W.verifier_verrou(d, lock)
    assert res["ok"] is True and res["verifiees"] == 1


def test_verifier_detecte_divergence(tmp_path):
    d = _wheelhouse(tmp_path, {"httpx-0.27.0-py3-none-any.whl": b"ZZZ"})
    lock = tmp_path / "lock.json"
    W.ecrire_verrou(d, lock)
    (d / "httpx-0.27.0-py3-none-any.whl").write_bytes(b"MODIFIEE")   # roue alteree
    res = W.verifier_verrou(d, lock)
    assert res["ok"] is False and "httpx-0.27.0-py3-none-any.whl" in res["divergentes"]


def test_verifier_detecte_manquante_et_surplus(tmp_path):
    d = _wheelhouse(tmp_path, {"a-1.0-py3-none-any.whl": b"A"})
    lock = tmp_path / "lock.json"
    W.ecrire_verrou(d, lock)
    (d / "a-1.0-py3-none-any.whl").unlink()                          # manquante
    (d / "b-2.0-py3-none-any.whl").write_bytes(b"B")                 # surplus (non attendue)
    res = W.verifier_verrou(d, lock)
    assert res["ok"] is False
    assert "a-1.0-py3-none-any.whl" in res["manquantes"]
    assert "b-2.0-py3-none-any.whl" in res["surplus"]


def test_cli_ecrire_et_verifier(tmp_path, capsys):
    d = _wheelhouse(tmp_path, {"rich-13.7.0-py3-none-any.whl": b"R"})
    lock = tmp_path / "lock.json"
    assert W.main(["--wheelhouse", str(d), "--ecrire", str(lock)]) == 0
    assert "WHEELHOUSE_LOCK ecrit" in capsys.readouterr().out
    assert W.main(["--wheelhouse", str(d), "--verifier", str(lock)]) == 0
