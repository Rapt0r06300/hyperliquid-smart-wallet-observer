"""Evidence-driven validation of an extracted HyperSmart portable release.

Hermetic checks use only the embedded interpreter.  The separate network
smoke is restricted to documented, read-only market-data endpoints and never
sends credentials, signatures or execution payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hl_observer.ops.archive_portable import (
    NOM_MANIFESTE,
    extraire_et_reverifier,
    extraire_zip_surement,
)

SCHEMA = "hypersmart.portable_validation.v1"
CI_SCHEMA = "hypersmart.ci_head_proof.v1"
NETWORK_ENDPOINTS = (
    ("hyperliquid", "POST", "https://api.hyperliquid.xyz/info", {"type": "allMids"}),
    ("binance", "GET", "https://api.binance.com/api/v3/time", None),
    ("dydx", "GET", "https://indexer.dydx.trade/v4/time", None),
)


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_from_archive(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive, "r") as bundle:
        return json.loads(bundle.read(NOM_MANIFESTE).decode("utf-8"))


def _hermetic_environment(root: Path, guard_dir: Path) -> dict[str, str]:
    python_dir = root / "tools" / "python"
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    writable = root / "runtime" / "portable-validation" / "environment"
    for name in ("tmp", "home", "appdata", "localappdata"):
        (writable / name).mkdir(parents=True, exist_ok=True)
    path_entries = [python_dir, python_dir / "Scripts", system_root / "System32"]
    python_path = [guard_dir, root / "src", root, root / "tools"]
    env = {
        "PATH": os.pathsep.join(str(path) for path in path_entries),
        "PYTHONPATH": os.pathsep.join(str(path) for path in python_path),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "TEMP": str(writable / "tmp"),
        "TMP": str(writable / "tmp"),
        "HOME": str(writable / "home"),
        "USERPROFILE": str(writable / "home"),
        "APPDATA": str(writable / "appdata"),
        "LOCALAPPDATA": str(writable / "localappdata"),
        "HYPERSMART_PORTABLE_AUDIT_ROOT": str(root),
        "HYPERSMART_PORTABLE_AUDIT_LOG": str(
            root / "runtime" / "portable-validation" / "audit_violations.jsonl"
        ),
        "HL_ENABLE_MAINNET_EXECUTION": "0",
        "HL_ENABLE_TESTNET_EXECUTION": "0",
        "REAL_MAINNET_TRADING": "false",
        "TESTNET_EXECUTION_ENABLED": "false",
        "HYPERSMART_RUNTIME_ROOT": str(root),
    }
    for name in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def _install_sitecustomize(guard_dir: Path) -> None:
    guard_dir.mkdir(parents=True, exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(
        "from hl_observer.ops.portable_audit_guard import install_from_environment\n"
        "install_from_environment()\n",
        encoding="utf-8",
        newline="\n",
    )


def _run(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command), cwd=str(cwd), env=dict(env), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
            stdin=subprocess.DEVNULL, check=False,
        )
        code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        timed_out = True
    return {
        "name": name,
        "ok": code == 0,
        "returncode": code,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "command": list(command),
        "stdout_tail": stdout[-12000:],
        "stderr_tail": stderr[-12000:],
    }


def _module_import_script(root: Path) -> str:
    return (
        "import importlib, json, pathlib\n"
        "root=pathlib.Path(" + repr(str(root)) + ")\n"
        "mods=[]\n"
        "for base,prefix in ((root/'src'/'hl_observer','hl_observer'),"
        "(root/'hyper_smart_observer','hyper_smart_observer')):\n"
        "  if not base.is_dir(): continue\n"
        "  for p in base.rglob('*.py'):\n"
        "    rel=p.relative_to(base)\n"
        "    if '__pycache__' in rel.parts: continue\n"
        "    parts=list(rel.with_suffix('').parts)\n"
        "    if parts[-1]=='__init__': parts=parts[:-1]\n"
        "    mod='.'.join([prefix]+parts)\n"
        "    if mod and mod not in mods: mods.append(mod)\n"
        "fail=[]\n"
        "for mod in sorted(mods):\n"
        "  try: importlib.import_module(mod)\n"
        "  except BaseException as exc: fail.append({'module':mod,'error':repr(exc)})\n"
        "print(json.dumps({'count':len(mods),'failures':fail},sort_keys=True))\n"
        "raise SystemExit(1 if fail else 0)\n"
    )


def _processes_for_root(root: Path) -> set[int]:
    try:
        import psutil
    except ImportError:
        return set()
    needle = str(root).casefold()
    found: set[int] = set()
    for process in psutil.process_iter(("pid", "cmdline")):
        try:
            cmdline = " ".join(process.info.get("cmdline") or []).casefold()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if needle in cmdline:
            found.add(int(process.info["pid"]))
    return found


def _process_scanner_available() -> bool:
    try:
        import psutil  # noqa: F401
    except ImportError:
        return False
    return True


def _ci_gate(manifest: Mapping[str, Any], proof: str | Path | None = None) -> dict[str, Any]:
    expected = str(manifest.get("git_sha", ""))
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        actual = os.environ.get("GITHUB_SHA", "")
        return {
            "ok": bool(expected and actual == expected),
            "provider": "github-actions-current-run",
            "git_sha": actual,
            "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        }
    if proof:
        try:
            payload = _json(Path(proof))
        except (OSError, ValueError) as exc:
            return {"ok": False, "detail": "CI proof unreadable: %s" % exc}
        ok = (
            payload.get("schema") == CI_SCHEMA
            and payload.get("provider") == "github-actions"
            and payload.get("conclusion") == "success"
            and payload.get("git_sha") == expected
            and bool(payload.get("run_id"))
        )
        return {"ok": ok, **payload}
    return {"ok": False, "detail": "exact-head GitHub Actions proof absent"}


def smoke_reseau_readonly(
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = 10.0,
) -> dict[str, Any]:
    results = []
    for venue, method, url, payload in NETWORK_ENDPOINTS:
        if "/exchange" in url.casefold() or not url.startswith("https://"):
            results.append({"venue": venue, "ok": False, "detail": "unsafe URL refused"})
            continue
        body = None if payload is None else json.dumps(payload).encode("ascii")
        headers = {"Content-Type": "application/json", "User-Agent": "HyperSmart-Portable-Smoke/1"}
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        started = time.monotonic()
        try:
            with opener(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024)
                status = int(getattr(response, "status", 200))
            parsed = json.loads(raw.decode("utf-8"))
            valid = isinstance(parsed, dict) and bool(parsed)
            results.append({
                "venue": venue, "ok": 200 <= status < 300 and valid,
                "status": status, "bytes": len(raw),
                "duration_seconds": round(time.monotonic() - started, 3),
                "url": url, "method": method,
            })
        except Exception as exc:  # noqa: BLE001 - evidence records bounded network failure
            results.append({"venue": venue, "ok": False, "url": url, "method": method,
                            "detail": repr(exc)})
    return {
        "ok": len(results) == len(NETWORK_ENDPOINTS) and all(row["ok"] for row in results),
        "read_only": True,
        "credentials_sent": False,
        "exchange_endpoint_used": False,
        "results": results,
    }


def valider_archive_portable(
    archive: str | Path,
    *,
    archive_repetition: str | Path | None = None,
    ci_proof: str | Path | None = None,
    network_opener: Callable[..., Any] = urllib.request.urlopen,
    extraction_parent: str | Path | None = None,
    pytest_timeout: int = 3600,
) -> dict[str, Any]:
    archive = Path(archive).resolve()
    manifest = _manifest_from_archive(archive)
    archive_sha, archive_size = _sha256(archive)
    repetition = Path(archive_repetition).resolve() if archive_repetition else None
    repeat_sha = _sha256(repetition)[0] if repetition and repetition.is_file() else ""
    reproducible = bool(repetition and repeat_sha == archive_sha)

    owned_parent = extraction_parent is None
    parent = Path(extraction_parent).resolve() if extraction_parent else Path(
        tempfile.mkdtemp(prefix="hspv-")
    ).resolve()
    extractions: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    primary: Path | None = None
    orphaned: list[int] = []
    try:
        names = ("simple", "avec espaces et accents éà", "chemin-long-" + "x" * 24)
        for index, name in enumerate(names):
            destination = parent / name
            with zipfile.ZipFile(archive, "r") as bundle:
                security = extraire_zip_surement(bundle, destination)
            disk = extraire_et_reverifier(archive, dossier_extraction=destination)
            result = {"path_kind": name, "ok": bool(disk.get("ok")),
                      "security": security, "disk": disk}
            extractions.append(result)
            if index == 0:
                primary = destination
        assert primary is not None
        validation_dir = primary / "runtime" / "portable-validation"
        guard_dir = primary / "tools" / "python" / "Lib" / "site-packages"
        validation_dir.mkdir(parents=True, exist_ok=True)
        _install_sitecustomize(guard_dir)
        env = _hermetic_environment(primary, guard_dir)
        python = primary / "tools" / "python" / "python.exe"
        if not python.is_file():
            raise RuntimeError("embedded tools/python/python.exe missing after extraction")
        process_scanner_available = _process_scanner_available()
        before = _processes_for_root(primary)
        commands.append(_run(
            "portable_runtime", [str(python), "tools/portable_runtime.py", "--root", str(primary),
                                 "check", "--require-embedded", "--json"],
            cwd=primary, env=env, timeout=180,
        ))
        commands.append(_run(
            "wheelhouse_lock", [str(python), "tools/wheelhouse_lock.py", "--wheelhouse",
                                "tools/wheelhouse", "--verifier", "tools/wheelhouse/WHEELHOUSE_LOCK.json",
                                "--requirements", "requirements-portable.txt"],
            cwd=primary, env=env, timeout=180,
        ))
        commands.append(_run(
            "imports", [str(python), "-c", _module_import_script(primary)],
            cwd=primary, env=env, timeout=900,
        ))
        commands.append(_run(
            "pytest_full", [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            "--basetemp", str(validation_dir / "pytest-temp")],
            cwd=primary, env=env, timeout=pytest_timeout,
        ))
        commands.append(_run(
            "safety_check", [str(python), "-m", "hyper_smart_observer.app.main", "--safety-check"],
            cwd=primary, env=env, timeout=300,
        ))
        commands.append(_run(
            "audit_safety", [str(python), "-m", "hyper_smart_observer.app.main", "--audit-safety"],
            cwd=primary, env=env, timeout=300,
        ))
        comspec = env.get("COMSPEC", "cmd.exe")
        commands.append(_run(
            "launcher", [comspec, "/d", "/c", "LANCER_HYPERSMART.cmd", "portable-check"],
            cwd=primary, env=env, timeout=300,
        ))
        report = primary / "runtime" / "reports" / "backtest_replay" / "RAPPORT_PORTABLE_SMOKE.json"
        previous_mtime = report.stat().st_mtime_ns if report.exists() else 0
        commands.append(_run(
            "analyser", [comspec, "/d", "/c", "ANALYSER_BACKTESTS_REPLAYS.cmd", "portable-smoke"],
            cwd=primary, env=env, timeout=300,
        ))
        smoke = _json(report) if report.is_file() and report.stat().st_mtime_ns > previous_mtime else {}
        time.sleep(0.2)
        after = _processes_for_root(primary)
        orphaned = sorted(after - before)
        audit_log = Path(env["HYPERSMART_PORTABLE_AUDIT_LOG"])
        violations = audit_log.read_text(encoding="utf-8").splitlines() if audit_log.is_file() else []
        network = smoke_reseau_readonly(opener=network_opener)
        analyser_command = next(row for row in commands if row["name"] == "analyser")
        analyser_ok = bool(
            analyser_command["ok"] and smoke
            and smoke.get("ledger_reconciliation", {}).get("ok")
            and smoke.get("session_closure", {}).get("statut") == "COMPLETE"
        )
        checks = {
            "hashes_extraits": {"ok": all(row["ok"] for row in extractions), "runs": extractions},
            "runtime_python": next(row for row in commands if row["name"] == "portable_runtime"),
            "wheelhouse_exact": next(row for row in commands if row["name"] == "wheelhouse_lock"),
            "modules_collecteurs": next(row for row in commands if row["name"] == "imports"),
            "tests_archive_extraite": next(row for row in commands if row["name"] == "pytest_full"),
            "audits_paper_only": {
                "ok": all(row["ok"] for row in commands if row["name"] in {"safety_check", "audit_safety"}),
                "commands": [row for row in commands if row["name"] in {"safety_check", "audit_safety"}],
            },
            "lanceur_hypersmart": next(row for row in commands if row["name"] == "launcher"),
            "analyseur_backtests": {
                **analyser_command,
                "ok": analyser_ok,
                "report_fresh": bool(smoke),
                "ledger_reconciled": bool(smoke.get("ledger_reconciliation", {}).get("ok")),
                "session_complete": smoke.get("session_closure", {}).get("statut") == "COMPLETE",
            },
            "test_hermetique_windows": {"ok": os.name == "nt" and all(row["ok"] for row in commands)},
            "zero_ecriture_externe": {"ok": not violations, "violations": violations},
            "zero_processus_orphelin": {
                "ok": process_scanner_available and not orphaned,
                "scanner_available": process_scanner_available,
                "pids": orphaned,
            },
            "smoke_reseau_readonly": network,
            "build_reproductible": {
                "ok": reproducible, "archive_sha256": archive_sha,
                "repetition_sha256": repeat_sha,
            },
            "ci_head_verte": _ci_gate(manifest, ci_proof),
        }
        ok = all(bool(value.get("ok")) for value in checks.values())
        return {
            "schema": SCHEMA,
            "ok": ok,
            "archive": archive.name,
            "archive_sha256": archive_sha,
            "archive_size": archive_size,
            "git_sha": manifest.get("git_sha", ""),
            "manifest_fingerprint": manifest.get("empreinte_globale", ""),
            "checks": checks,
            "commands": commands,
            "paper_read_only": True,
            "real_execution": False,
        }
    finally:
        if owned_parent:
            shutil.rmtree(parent, ignore_errors=True)


def write_evidence(path: str | Path, payload: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(".%s.%d.tmp" % (destination.name, os.getpid()))
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    os.replace(temporary, destination)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate one extracted portable archive")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--archive-repetition", default="")
    parser.add_argument("--ci-proof", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--pytest-timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    try:
        result = valider_archive_portable(
            args.archive,
            archive_repetition=args.archive_repetition or None,
            ci_proof=args.ci_proof or None,
            pytest_timeout=args.pytest_timeout,
        )
        write_evidence(args.output, result)
    except Exception as exc:  # noqa: BLE001 - CLI reports a bounded validation failure
        failure = {"schema": SCHEMA, "ok": False, "error": repr(exc)}
        write_evidence(args.output, failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


__all__ = [
    "CI_SCHEMA", "NETWORK_ENDPOINTS", "SCHEMA", "smoke_reseau_readonly",
    "valider_archive_portable", "write_evidence",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
