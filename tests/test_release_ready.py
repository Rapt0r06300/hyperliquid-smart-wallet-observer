"""[RELEASE item 14] Verdict unique RELEASE_READY, fail-closed. FALSE tant qu'une porte n'est pas
prouvee : embed Python+DLL+wheels, modules runtime, manifeste+hashes, lock wheelhouse, tests/CI/
hermetique/ecritures (entrees externes). TRUE seulement quand TOUT est vert. 0 reseau.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.ops import release_ready as RR            # noqa: E402
import wheelhouse_lock as WL                                # noqa: E402


def test_false_sur_checkout_sans_embed(tmp_path):
    # un checkout nu (pas d'embed, pas de wheelhouse, pas de manifeste) -> RELEASE_READY false.
    v = RR.evaluer_release(tmp_path)
    assert v["RELEASE_READY"] is False
    assert "python_embarque" in v["manquants"] and "wheelhouse" in v["manquants"]


def test_false_meme_avec_embed_si_preuves_externes_absentes(tmp_path):
    _release_complete_locale(tmp_path)
    # tout le local est OK, mais tests/CI/hermetique/ecritures pas encore prouves -> toujours false.
    v = RR.evaluer_release(tmp_path, importateur=lambda m: None)
    assert v["RELEASE_READY"] is False
    assert set(v["manquants"]) <= {"tests_verts", "ci_head_verte",
                                   "test_hermetique_windows", "zero_ecriture_externe"}
    assert "python_embarque" not in v["manquants"]         # local prouve


def test_true_quand_tout_est_vert(tmp_path):
    _release_complete_locale(tmp_path)
    v = RR.evaluer_release(tmp_path, importateur=lambda m: None, tests_verts=True, ci_verte=True,
                           hermetique_ok=True, aucune_ecriture_externe=True)
    assert v["RELEASE_READY"] is True and v["manquants"] == []


def test_cli_code_sortie(tmp_path, capsys):
    code = RR.main(["--racine", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1 and "RELEASE_READY = false" in out    # fail-closed


def _release_complete_locale(root: Path):
    """Fabrique un dossier ou TOUTES les portes LOCALES sont vertes (embed+wheelhouse+manifeste)."""
    # embed Python + DLL
    d = root / "tools" / "python"
    d.mkdir(parents=True)
    (d / "python.exe").write_bytes(b"MZ")
    (d / "python314.dll").write_bytes(b"MZ")
    # wheelhouse + lock verifie
    wh = root / "tools" / "wheelhouse"
    wh.mkdir(parents=True)
    (wh / "rich-13.7-py3-none-any.whl").write_bytes(b"WHEEL")
    WL.ecrire_verrou(wh, wh / "WHEELHOUSE_LOCK.json")
    # manifeste avec hashes + empreinte
    (root / "PORTABLE_MANIFEST.json").write_text(json.dumps({
        "schema": "hypersmart.portable_manifest.v1", "empreinte_globale": "abc123",
        "fichiers": {"src/app.py": {"sha256": "d" * 64, "taille": 3}},
    }), encoding="utf-8")
