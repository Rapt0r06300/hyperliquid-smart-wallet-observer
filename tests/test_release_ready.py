"""Regression tests for the evidence-driven portable release verdict."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from hl_observer.ops import release_ready as RR  # noqa: E402
import wheelhouse_lock as WL  # noqa: E402


def _hash(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def _release_complete(root: Path) -> tuple[dict, Path]:
    runtime = root / "tools" / "python"
    (runtime / "Lib" / "site-packages" / "certifi").mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"MZ")
    (runtime / "python314.dll").write_bytes(b"MZdll")
    (runtime / "_ssl.pyd").write_bytes(b"MZpyd")
    (runtime / "Lib" / "site-packages" / "certifi" / "cacert.pem").write_text(
        "-----BEGIN CERTIFICATE-----\nPUBLIC\n-----END CERTIFICATE-----\n", encoding="ascii"
    )
    wheelhouse = root / "tools" / "wheelhouse"
    wheelhouse.mkdir(parents=True)
    wheel = wheelhouse / "rich-13.7-py3-none-any.whl"
    wheel.write_bytes(b"WHEEL")
    wheel_sha = hashlib.sha256(b"WHEEL").hexdigest()
    WL.ecrire_verrou(wheelhouse, wheelhouse / "WHEELHOUSE_LOCK.json")
    (root / "requirements-portable.txt").write_text(
        "rich==13.7 --hash=sha256:%s\n" % wheel_sha, encoding="ascii"
    )
    (root / "tools" / "wheelhouse_lock.py").write_bytes(
        (ROOT / "tools" / "wheelhouse_lock.py").read_bytes()
    )
    app = root / "src" / "app.py"
    app.parent.mkdir(parents=True)
    app.write_text("VALUE = 1\n", encoding="ascii")
    digest, size = _hash(app)
    files = {"src/app.py": {"sha256": digest, "taille": size}}
    fingerprint = RR._manifest_fingerprint(files)
    manifest = {
        "schema": "hypersmart.portable_manifest.v1",
        "git_sha": "a" * 40,
        "empreinte_globale": fingerprint,
        "fichiers": files,
    }
    (root / "PORTABLE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    checks = {
        name: {"ok": True, "detail": "proved"}
        for name in (
            "modules_collecteurs", "tests_archive_extraite", "audits_paper_only",
            "lanceur_hypersmart", "analyseur_backtests", "test_hermetique_windows",
            "zero_ecriture_externe", "zero_processus_orphelin", "smoke_reseau_readonly",
            "build_reproductible", "ci_head_verte",
        )
    }
    evidence = root / "PORTABLE_VALIDATION.json"
    evidence.write_text(json.dumps({
        "schema": "hypersmart.portable_validation.v1",
        "git_sha": manifest["git_sha"],
        "manifest_fingerprint": fingerprint,
        "paper_read_only": True,
        "real_execution": False,
        "checks": checks,
    }), encoding="utf-8")
    return manifest, evidence


def test_bare_checkout_is_fail_closed(tmp_path):
    verdict = RR.evaluer_release(tmp_path)
    assert verdict["RELEASE_READY"] is False
    assert "python_embarque" in verdict["manquants"]
    assert "preuve_liee_archive" in verdict["manquants"]


def test_local_bytes_are_not_enough_without_bound_evidence(tmp_path):
    _release_complete(tmp_path)
    verdict = RR.evaluer_release(tmp_path)
    assert verdict["RELEASE_READY"] is False
    assert "preuve_liee_archive" in verdict["manquants"]
    assert "python_embarque" not in verdict["manquants"]
    assert "wheelhouse_exact" not in verdict["manquants"]


def test_all_gates_can_only_pass_with_matching_evidence(tmp_path):
    _manifest, evidence = _release_complete(tmp_path)
    verdict = RR.evaluer_release(tmp_path, preuve=evidence)
    assert verdict["RELEASE_READY"] is True
    assert verdict["manquants"] == []


def test_tampered_file_and_wrong_evidence_binding_are_rejected(tmp_path):
    _manifest, evidence = _release_complete(tmp_path)
    (tmp_path / "src" / "app.py").write_text("VALUE = 2\n", encoding="ascii")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["git_sha"] = "b" * 40
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    verdict = RR.evaluer_release(tmp_path, preuve=evidence)
    assert "manifeste_complet" in verdict["manquants"]
    assert "preuve_liee_archive" in verdict["manquants"]


def test_cli_has_no_declarative_green_switches(tmp_path, capsys):
    assert RR.main(["--racine", str(tmp_path)]) == 1
    assert "RELEASE_READY = false" in capsys.readouterr().out
    try:
        RR.main(["--racine", str(tmp_path), "--tests-verts"])
    except SystemExit as exc:
        assert exc.code != 0
    else:  # pragma: no cover - regression guard
        raise AssertionError("declarative green switch was accepted")
