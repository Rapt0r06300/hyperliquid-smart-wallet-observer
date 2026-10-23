"""Readable, local-only Copy-Vault test launcher and freeze status report."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.sous_processus_isole import creationflags

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CORE_TESTS = (
    "tests/test_copy_vault_v21_frozen.py",
    "tests/test_copy_vault_executable.py",
)
INTEGRATION_TESTS = (
    "tests/test_alina_quant_lab_console.py",
    "tests/test_train_statistics.py",
    "tests/test_economic_campaigns.py",
    "tests/test_economic_proof_audit.py",
    "tests/test_replay_compatibility.py",
    "tests/test_manifest_policy.py",
    "tests/test_funding_settlement_period_guard.py",
    "tests/test_no_mainnet_execution.py",
    "tests/test_paper_trading_import_boundaries.py",
    "tests/test_unknown_execution_code_quarantine.py",
)


def assess_physical_freeze(path: Path) -> dict[str, Any]:
    """Read and validate the physical Copy-Vault freeze without changing it."""
    if not path.is_file():
        return {"status": "MISSING", "reason": "PHYSICAL_FREEZE_NOT_FOUND"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "INVALID", "reason": f"FREEZE_READ_ERROR:{type(exc).__name__}"}
    try:
        from hl_observer.backtesting.copy_vault_v21_frozen import _verified_freeze

        verified = _verified_freeze(payload)
    except (TypeError, ValueError) as exc:
        return {"status": "REJECTED", "reason": str(exc), "path": str(path)}
    parameters = verified["parameters"]
    return {
        "status": "VALID_PHYSICAL_FREEZE",
        "reason": None,
        "path": str(path),
        "campaign_id": verified.get("campaign_id"),
        "parameters_sha256": verified.get("parameters_sha256"),
        "core_notional_usd": parameters.get("core_notional_usd"),
        "probe_notional_usd": parameters.get("probe_notional_usd"),
    }


def _windows_process_metrics(pid: int) -> tuple[int | None, float | None]:
    """Return process working-set bytes and CPU seconds when Windows APIs allow it."""
    if os.name != "nt":
        return None, None

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            ctypes.c_ulong,
            ctypes.c_bool,
            ctypes.c_ulong,
        ]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.GetProcessTimes.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
            ctypes.POINTER(FileTime),
        ]
        kernel32.GetProcessTimes.restype = ctypes.c_int
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(MemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
        if not handle:
            return None, None
        try:
            counters = MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            memory_ok = psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            creation, exit_time, kernel_time, user_time = (
                FileTime(), FileTime(), FileTime(), FileTime()
            )
            cpu_ok = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            )
            cpu_seconds = None
            if cpu_ok:
                kernel_ticks = (kernel_time.high << 32) | kernel_time.low
                user_ticks = (user_time.high << 32) | user_time.low
                cpu_seconds = (kernel_ticks + user_ticks) / 10_000_000
            return (
                int(counters.WorkingSetSize) if memory_ok else None,
                cpu_seconds,
            )
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None


def _test_groups() -> list[tuple[str, list[str]]]:
    all_copy = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").glob("test_copy_vault_*.py")
    )
    core = [path for path in CORE_TESTS if path in all_copy]
    remaining_copy = [path for path in all_copy if path not in core]
    integrations = [
        path for path in INTEGRATION_TESTS if (ROOT / path).is_file()
    ]
    return [
        ("Moteur V21 et exécution L2", core),
        ("Famille Copy-Vault complète", remaining_copy),
        ("Intégration économique, replay et sécurité PAPER", integrations),
    ]


def _pytest_counts(output: str) -> dict[str, int]:
    keys = ("passed", "failed", "errors", "skipped", "xfailed", "xpassed")
    counts = {key: 0 for key in keys}
    for key in keys:
        match = re.search(r"\b(\d+)\s+" + key + r"\b", output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _restore_processes() -> list[str]:
    if os.name != "nt":
        return []
    command = (
        "$p=Get-CimInstance Win32_Process | Where-Object { "
        "$_.Name -match '^(py|python)([.]exe)?$' -and "
        "$_.CommandLine -match 'sync_complete_clone[.]py|restore_alina[.]py' }; "
        "$p | ForEach-Object { '{0} {1}' -f $_.ProcessId,$_.Name }"
    )
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return []
    try:
        result = subprocess.run(
            [shell, "-NoProfile", "-Command", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _run_group(name: str, tests: list[str], log_path: Path) -> dict[str, Any]:
    print(f"\n{'=' * 76}\nÉTAPE : {name}\nTests concernés : {len(tests)} fichier(s)", flush=True)
    if not tests:
        print("ÉTAPE IGNORÉE : aucun test correspondant trouvé.", flush=True)
        return {"name": name, "status": "SKIPPED", "return_code": 0, "seconds": 0.0}

    command = [sys.executable, "-m", "pytest", "-vv", "-ra", *tests]
    print("Commande : " + subprocess.list2cmdline(command), flush=True)
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags(),
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [str(ROOT / "src"), str(ROOT), str(ROOT / "tools")]
            ),
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
            "HL_ENABLE_MAINNET_EXECUTION": "0",
            "HL_ENABLE_TESTNET_EXECUTION": "0",
            "REAL_MAINNET_TRADING": "false",
            "TESTNET_ONLY": "true",
        },
    )
    peak_working_set = 0
    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        output_lines.append(line)
        working_set, _cpu = _windows_process_metrics(process.pid)
        if working_set is not None:
            peak_working_set = max(peak_working_set, working_set)
    return_code = process.wait()
    elapsed = time.perf_counter() - started
    _, cpu_seconds = _windows_process_metrics(process.pid)
    full_output = "".join(output_lines)
    log_path.write_text(full_output, encoding="utf-8")
    counts = _pytest_counts(full_output)
    status = "PASS" if return_code == 0 else "FAIL"
    memory_text = (
        f"{peak_working_set / (1024 * 1024):.1f} MiB"
        if peak_working_set
        else "non disponible"
    )
    cpu_text = f"{cpu_seconds:.1f} s" if cpu_seconds is not None else "non disponible"
    print(
        f"\nBILAN ÉTAPE : {status} | durée {elapsed:.1f} s | "
        f"{counts['passed']} passés, {counts['failed']} échecs, "
        f"{counts['errors']} erreurs, {counts['skipped']} ignorés | "
        f"CPU {cpu_text} | mémoire de travail max {memory_text}",
        flush=True,
    )
    return {
        "name": name,
        "status": status,
        "return_code": return_code,
        "counts": counts,
        "seconds": round(elapsed, 3),
        "cpu_seconds": round(cpu_seconds, 3) if cpu_seconds is not None else None,
        "peak_working_set_bytes": peak_working_set or None,
        "log": str(log_path),
    }


def run_lab(*, preflight_only: bool = False) -> int:
    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    report_dir = ROOT / "runtime" / "reports" / "copy_vault_quant_lab" / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    freeze_path = ROOT / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json"
    freeze = assess_physical_freeze(freeze_path)
    head_run = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    head = head_run.stdout.strip() if head_run.returncode == 0 else "INCONNU"
    restore_processes = _restore_processes()

    print("ALINA SMART FLOW — LABORATOIRE QUANT LOCAL", flush=True)
    print("PAPER / READ-ONLY : aucun ordre, aucune collecte, aucun téléchargement.", flush=True)
    print(f"Dépôt : {ROOT}\nHEAD : {head}", flush=True)
    print("\nMODULES LOCAUX DÉTECTÉS", flush=True)
    for relative in (
        "src/hl_observer/backtesting/copy_vault_v21_frozen.py",
        "src/hl_observer/backtesting/copy_vault_executable.py",
        "src/hl_observer/backtesting/copy_vault_book_loader.py",
        "tests/test_copy_vault_v21_frozen.py",
        "tests/test_copy_vault_executable.py",
    ):
        state = "PRÉSENT" if (ROOT / relative).is_file() else "ABSENT"
        print(f"  [{state}] {relative}", flush=True)

    if freeze["status"] == "VALID_PHYSICAL_FREEZE":
        freeze_verdict = "FREEZE PHYSIQUE VALIDE — à confirmer économiquement par VALIDATION/OOS/FORWARD."
    else:
        freeze_verdict = (
            "AUCUNE STRATÉGIE MEILLEURE N'EST PROUVÉE GELÉE. Le freeze physique local "
            f"est {freeze['status']} : {freeze.get('reason')}"
        )
    print(f"\nVERDICT FREEZE : {freeze_verdict}", flush=True)
    if restore_processes:
        print(
            "\nRESTAURATION SAFE : processus toujours actifs; le lanceur ne les arrête pas : "
            + ", ".join(restore_processes),
            flush=True,
        )
    else:
        print("\nRESTAURATION SAFE : aucun processus de restauration détecté.", flush=True)

    groups: list[dict[str, Any]] = []
    if not preflight_only:
        for index, (name, tests) in enumerate(_test_groups(), start=1):
            print(f"\nPROGRESSION GLOBALE : étape {index}/3", flush=True)
            groups.append(
                _run_group(name, tests, report_dir / f"etape-{index}.log")
            )
    else:
        print("\nMode pré-vérification : les tests n'ont pas été lancés.", flush=True)

    failures = [row for row in groups if row["status"] == "FAIL"]
    summary = {
        "run_id": run_id,
        "head": head,
        "paper_read_only": True,
        "network_or_collection_started": False,
        "freeze": freeze,
        "freeze_verdict": freeze_verdict,
        "restore_processes_detected": restore_processes,
        "test_groups": groups,
        "status": "FAIL" if failures else ("PREFLIGHT_ONLY" if preflight_only else "PASS"),
    }
    (report_dir / "resultat.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_lines = [
        "# Rapport du laboratoire quant Copy-Vault",
        "",
        f"- Exécution UTC : {run_id}",
        f"- HEAD testé : `{head}`",
        "- Mode : PAPER / READ-ONLY; aucune collecte ni analyse économique de production lancée.",
        f"- Verdict freeze : {freeze_verdict}",
        f"- Freeze vérifié : `{freeze.get('path', freeze_path)}`",
        f"- Statut global des tests : **{summary['status']}**",
        "",
        "## Groupes de tests",
        "",
    ]
    report_lines.extend(
        f"- {row['status']} — {row['name']} : "
        f"{row.get('counts', {}).get('passed', 0)} passés, "
        f"{row.get('counts', {}).get('failed', 0)} échecs, "
        f"{row.get('counts', {}).get('errors', 0)} erreurs "
        f"({row['seconds']:.1f} s); journal : {row.get('log', '')}"
        for row in groups
    )
    report_lines.extend(
        [
            "",
            "## Interprétation",
            "",
            "Une suite verte valide le comportement logiciel couvert, pas la rentabilité. "
            "Aucune stratégie n'est déclarée meilleure sans un freeze valide et des preuves "
            "comparables en validation, OOS et forward. Les scénarios de capital restent diagnostics.",
            "",
        ]
    )
    (report_dir / "RAPPORT.md").write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\nRAPPORT DÉTAILLÉ : {report_dir / 'RAPPORT.md'}", flush=True)
    print(f"RÉSULTAT JSON : {report_dir / 'resultat.json'}", flush=True)
    if preflight_only:
        final_verdict = "pré-vérification terminée; les tests n'ont pas été lancés."
    elif failures:
        final_verdict = "ÉCHEC TESTS — consulter les journaux."
    else:
        final_verdict = "tests exécutés sans échec."
    print("VERDICT FINAL : " + final_verdict, flush=True)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="inspecte les modules et le freeze, sans lancer les tests",
    )
    args = parser.parse_args(argv)
    return run_lab(preflight_only=args.preflight_only)


if __name__ == "__main__":
    raise SystemExit(main())
