"""Fail-closed RELEASE_READY verdict for an extracted portable release.

No command-line switch can declare a gate successful.  Local gates are
recomputed from extracted bytes; runtime gates are accepted only from a
validation evidence file cryptographically bound to the same manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.ops.archive_portable import NOM_MANIFESTE, SCHEMA_MANIFESTE
from hl_observer.ops.validation_portable import SCHEMA as VALIDATION_SCHEMA


def _gate(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"gate": name, "ok": bool(ok), "detail": detail}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object")
    return payload


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _manifest_fingerprint(files: Mapping[str, Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(str(files[relative].get("sha256", "")).encode("utf-8"))
    return digest.hexdigest()


def _embedded_runtime(root: Path) -> dict[str, Any]:
    directory = root / "tools" / "python"
    exe = directory / "python.exe"
    dlls = sorted(directory.glob("python*.dll"))
    pyd = sorted(directory.rglob("*.pyd"))
    site_packages = directory / "Lib" / "site-packages"
    certs = sorted(
        path for path in directory.rglob("*.pem")
        if "PRIVATE KEY" not in path.read_text(encoding="utf-8", errors="ignore")
    )
    ok = exe.is_file() and bool(dlls) and bool(pyd) and site_packages.is_dir() and bool(certs)
    return _gate(
        "python_embarque", ok,
        "python.exe=%s dll=%d pyd=%d site-packages=%s certificats=%d"
        % (exe.is_file(), len(dlls), len(pyd), site_packages.is_dir(), len(certs)),
    )


def _load_wheel_verifier(root: Path):
    path = root / "tools" / "wheelhouse_lock.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("hypersmart_extracted_wheelhouse_lock", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verifier_verrou


def _wheelhouse(root: Path) -> dict[str, Any]:
    directory = root / "tools" / "wheelhouse"
    lock = directory / "WHEELHOUSE_LOCK.json"
    requirements = root / "requirements-portable.txt"
    verifier = _load_wheel_verifier(root)
    if verifier is None or not lock.is_file() or not requirements.is_file():
        return _gate("wheelhouse_exact", False, "verifier, lock ou requirements absent")
    try:
        result = verifier(directory, lock, requirements)
    except Exception as exc:  # noqa: BLE001 - corrupt extracted release is a failed gate
        return _gate("wheelhouse_exact", False, "verification impossible: %s" % exc)
    return _gate(
        "wheelhouse_exact", bool(result.get("ok")),
        "%d wheels verifiees; manquantes=%d divergentes=%d surplus=%d"
        % (
            result.get("verifiees", 0), len(result.get("manquantes", [])),
            len(result.get("divergentes", [])), len(result.get("surplus", [])),
        ),
    )


def _manifest(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / NOM_MANIFESTE
    try:
        manifest = _load_json(path)
    except (OSError, ValueError) as exc:
        return {}, _gate("manifeste_complet", False, "manifest unreadable: %s" % exc)
    files = manifest.get("fichiers")
    if manifest.get("schema") != SCHEMA_MANIFESTE or not isinstance(files, dict) or not files:
        return manifest, _gate("manifeste_complet", False, "schema/files invalid")
    missing: list[str] = []
    divergent: list[str] = []
    for relative, metadata in files.items():
        candidate = root / relative
        if not candidate.is_file():
            missing.append(relative)
            continue
        digest, size = _sha256(candidate)
        if digest != metadata.get("sha256") or size != metadata.get("taille"):
            divergent.append(relative)
    expected_fingerprint = _manifest_fingerprint(files)
    fingerprint_ok = expected_fingerprint == manifest.get("empreinte_globale")
    ok = not missing and not divergent and fingerprint_ok
    return manifest, _gate(
        "manifeste_complet", ok,
        "files=%d missing=%d divergent=%d fingerprint=%s"
        % (len(files), len(missing), len(divergent), fingerprint_ok),
    )


def _evidence(path: str | Path | None) -> tuple[dict[str, Any], str]:
    if not path:
        return {}, "validation evidence absent"
    try:
        payload = _load_json(Path(path))
    except (OSError, ValueError) as exc:
        return {}, "validation evidence unreadable: %s" % exc
    if payload.get("schema") != VALIDATION_SCHEMA:
        return {}, "validation evidence schema invalid"
    return payload, "validation evidence loaded"


def _check_from_evidence(evidence: Mapping[str, Any], key: str, gate_name: str | None = None) -> dict:
    item = evidence.get("checks", {}).get(key, {}) if evidence else {}
    detail = item.get("detail") or item.get("stderr_tail") or item.get("stdout_tail") or "proof absent"
    return _gate(gate_name or key, bool(item.get("ok")), str(detail)[-2000:])


def evaluer_release(root: str | Path, *, preuve: str | Path | None = None) -> dict[str, Any]:
    """Evaluate extracted bytes and bound evidence; every missing gate fails."""
    root = Path(root).resolve()
    manifest, manifest_gate = _manifest(root)
    evidence, evidence_detail = _evidence(preuve)
    binding_ok = bool(
        manifest
        and evidence
        and evidence.get("git_sha") == manifest.get("git_sha")
        and evidence.get("manifest_fingerprint") == manifest.get("empreinte_globale")
        and evidence.get("paper_read_only") is True
        and evidence.get("real_execution") is False
    )
    gates = [
        _embedded_runtime(root),
        _wheelhouse(root),
        manifest_gate,
        _gate("preuve_liee_archive", binding_ok, evidence_detail),
        _check_from_evidence(evidence, "modules_collecteurs"),
        _check_from_evidence(evidence, "tests_archive_extraite"),
        _check_from_evidence(evidence, "audits_paper_only"),
        _check_from_evidence(evidence, "lanceur_hypersmart"),
        _check_from_evidence(evidence, "analyseur_backtests"),
        _check_from_evidence(evidence, "test_hermetique_windows"),
        _check_from_evidence(evidence, "zero_ecriture_externe"),
        _check_from_evidence(evidence, "zero_processus_orphelin"),
        _check_from_evidence(evidence, "smoke_reseau_readonly"),
        _check_from_evidence(evidence, "build_reproductible"),
        _check_from_evidence(evidence, "ci_head_verte"),
    ]
    missing = [gate["gate"] for gate in gates if not gate["ok"]]
    return {
        "RELEASE_READY": not missing,
        "manquants": missing,
        "gates": gates,
        "git_sha": manifest.get("git_sha", ""),
        "manifest_fingerprint": manifest.get("empreinte_globale", ""),
    }


def formater(verdict: Mapping[str, Any]) -> str:
    lines = ["RELEASE_READY = %s" % ("true" if verdict["RELEASE_READY"] else "false")]
    for gate in verdict["gates"]:
        lines.append("  [%s] %-28s %s" % (
            "OK" if gate["ok"] else "  ", gate["gate"], gate["detail"],
        ))
    if verdict["manquants"]:
        lines.append("  -> bloque par : %s" % ", ".join(verdict["manquants"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-driven RELEASE_READY verdict")
    parser.add_argument("--racine", default=".", help="extracted release root")
    parser.add_argument("--preuve", default="", help="PORTABLE_VALIDATION.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    verdict = evaluer_release(args.racine, preuve=args.preuve or None)
    print(json.dumps(verdict, ensure_ascii=False, indent=2) if args.json else formater(verdict))
    return 0 if verdict["RELEASE_READY"] else 1


__all__ = ["evaluer_release", "formater", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
