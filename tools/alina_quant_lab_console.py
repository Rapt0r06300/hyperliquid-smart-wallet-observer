"""Readable, local-only Copy-Vault test launcher and freeze status report."""
from __future__ import annotations

import argparse
import ctypes
import html
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.sous_processus_isole import creationflags  # noqa: E402

CORE_TESTS = (
    "tests/test_copy_vault_v21_frozen.py",
    "tests/test_copy_vault_executable.py",
)
INTEGRATION_TESTS = (
    "tests/test_alina_quant_lab_console.py",
    "tests/test_paper_canonique.py",
    "tests/test_strategy_readiness.py",
    "tests/test_readme_scope_coherence.py",
    "tests/test_active_strategy_scope_v2.py",
    "tests/test_scope_source_unique.py",
    "tests/test_simulation_readiness.py",
    "tests/test_ui_simulation_status_fast.py",
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


def _ensure_copy_vault_alinasync(root: Path) -> int:
    """Restore the full current SAFE Copy-Vault selection, with no byte cap."""
    command = [
        sys.executable, "-u", str(root / "tools" / "sync_complete_clone.py"),
        "--skip-update", "--download-safe", "--all-safe",
        "--family", "copy_vault_fills",
        "--family", "copy_vault_snapshot",
        "--family", "copy_vault_l2",
    ]
    print(
        "ALINASYNC_COPY_VAULT_RESTORE=" + subprocess.list2cmdline(command),
        flush=True,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            env={
                **os.environ,
                "HL_ENABLE_MAINNET_EXECUTION": "0",
                "HL_ENABLE_TESTNET_EXECUTION": "0",
                "REAL_MAINNET_TRADING": "false",
                "TESTNET_ONLY": "true",
            },
        )
    except OSError as exc:
        print(f"ALINASYNC_COPY_VAULT_NO_GO: {exc}", flush=True)
        return 2
    return int(completed.returncode)


def inspect_local_safe_corpus(root: Path) -> dict[str, Any]:
    """Read-only AlinaSync archive receipt check; not economic source certification."""
    recovery = root / "runtime" / "recovery" / "full"
    result: dict[str, Any] = {
        "status": "NOT_CERTIFIED",
        "safe_registry_rows": None,
        "restore_catalog_sha256": None,
        "active_catalog_sha256": None,
    }
    try:
        restored = json.loads((recovery / "RESTORE_REPORT.json").read_text(encoding="utf-8"))
        classification = restored.get("classification") or {}
        registry = recovery / "SAFE_SHARDS.sqlite3"
        catalog = (restored.get("catalog_verification") or {}).get("source_index_sha256")
        if not (
            restored.get("status") == "REPLAY_READY_COMPLETE"
            and classification.get("materialization_complete") is True
            and type(classification.get("usable_shards")) is int
            and classification["usable_shards"] > 0
            and isinstance(catalog, str) and len(catalog) == 64
            and registry.is_file() and not registry.is_symlink()
        ):
            return result
        with sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0) as db:
            count = db.execute("SELECT COUNT(*) FROM current_safe_shards").fetchone()[0]
        expected = classification["usable_shards"]
        catalog_path = root / "catalog" / "DATA_INDEX.json"
        digest = hashlib.sha256()
        with catalog_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        active_catalog = digest.hexdigest()
        if type(count) is not int or count != expected:
            status = "REGISTRY_COUNT_MISMATCH"
        elif active_catalog != catalog:
            status = "STALE_CATALOG"
        else:
            status = "RESTORE_RECEIPTS_MATCH_NOT_REHASHED"
        return {
            "status": status,
            "safe_registry_rows": int(count),
            "restore_catalog_sha256": catalog,
            "active_catalog_sha256": active_catalog,
        }
    except (OSError, ValueError, TypeError, sqlite3.Error, AttributeError):
        return result


def assess_physical_freeze(path: Path) -> dict[str, Any]:
    """Read and validate the physical Copy-Vault freeze without changing it."""
    if not path.is_file():
        return {"status": "MISSING", "reason": "PHYSICAL_FREEZE_NOT_FOUND"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "INVALID", "reason": f"FREEZE_READ_ERROR:{type(exc).__name__}"}
    freeze_root = payload.get("freeze") if isinstance(payload, dict) else None
    parameters = freeze_root.get("parameters") if isinstance(freeze_root, dict) else None
    if not isinstance(parameters, dict):
        parameters = {}
    configured = {
        "core_notional_usd": parameters.get("core_notional_usd"),
        "probe_notional_usd": parameters.get("probe_notional_usd"),
        "configured_daily_profit_lock_usd": parameters.get("daily_profit_lock_usd"),
    }
    try:
        from hl_observer.backtesting.copy_vault_v21_frozen import _verified_freeze

        verified = _verified_freeze(payload)
    except (TypeError, ValueError) as exc:
        return {
            "status": "REJECTED", "reason": str(exc), "path": str(path), **configured,
        }
    parameters = verified["parameters"]
    return {
        "status": "VALID_PHYSICAL_FREEZE",
        "reason": None,
        "path": str(path),
        "campaign_id": verified.get("campaign_id"),
        "parameters_sha256": verified.get("parameters_sha256"),
        "core_notional_usd": parameters.get("core_notional_usd"),
        "probe_notional_usd": parameters.get("probe_notional_usd"),
        "configured_daily_profit_lock_usd": parameters.get("daily_profit_lock_usd"),
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
        label = r"errors?" if key == "errors" else re.escape(key)
        match = re.search(r"\b(\d+)\s+" + label + r"\b", output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _pytest_parallel_args(test_file_count: int) -> list[str]:
    """Use all logical CPU groups while bounding workers to the requested share."""

    if importlib.util.find_spec("xdist") is None or test_file_count <= 1:
        return []
    try:
        percent = int(os.environ.get("ALINA_QUANT_CPU_PERCENT", "65"))
    except ValueError:
        percent = 65
    percent = min(100, max(1, percent))
    logical_cpus = max(1, int(os.cpu_count() or 1))
    workers = max(1, logical_cpus * percent // 100)
    workers = min(workers, max(1, int(test_file_count)))
    return ["-n", str(workers), "--dist", "loadfile"]


def _terminate_test_process_tree(process: subprocess.Popen[str]) -> None:
    """Stop only the current pytest tree so Ctrl+C can still write the report."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _write_html_report(report_dir: Path, summary: dict[str, Any]) -> Path:
    """Write the human-facing local dashboard from the same truthful result JSON."""

    economic = dict(summary.get("economic_result") or {})
    groups = list(summary.get("test_groups") or [])
    status = str(summary.get("status") or "UNKNOWN")
    status_class = "ok" if status == "PASS" else ("warn" if status == "INTERRUPTED" else "bad")
    cards = []
    for row in groups:
        counts = dict(row.get("counts") or {})
        row_status = str(row.get("status") or "UNKNOWN")
        row_class = "ok" if row_status == "PASS" else ("warn" if row_status == "INTERRUPTED" else "bad")
        cards.append(
            "<article class='card'>"
            f"<h3>{html.escape(str(row.get('name') or 'Étape'))}</h3>"
            f"<p class='status {row_class}'>{html.escape(row_status)}</p>"
            f"<p><b>{int(counts.get('passed') or 0)}</b> réussis · "
            f"<b>{int(counts.get('failed') or 0)}</b> échecs · "
            f"<b>{int(counts.get('errors') or 0)}</b> erreurs</p>"
            f"<p>Durée : {float(row.get('seconds') or 0):.1f} s</p>"
            f"<p class='path'>Journal : {html.escape(str(row.get('log') or ''))}</p>"
            "</article>"
        )
    target = report_dir / "RAPPORT.html"
    page = (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Laboratoire CopyVault</title><style>"
        ":root{color-scheme:dark}body{font:16px system-ui;margin:0;background:#09111f;color:#e7edf7}"
        "main{max-width:1050px;margin:auto;padding:32px}h1{margin-bottom:6px}.muted{color:#9fb0c8}"
        ".hero,.card{background:#111d30;border:1px solid #29405f;border-radius:14px;padding:20px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin:18px 0}"
        ".status{font-weight:800;font-size:1.15rem}.ok{color:#54e38e}.warn{color:#ffd166}.bad{color:#ff6b7a}"
        ".answer{font-size:1.25rem}.path{overflow-wrap:anywhere;color:#9fb0c8}"
        "code{color:#8fd3ff}li{margin:.5rem 0}</style></head><body><main>"
        "<h1>Laboratoire CopyVault</h1>"
        f"<p class='muted'>Run {html.escape(str(summary.get('run_id') or ''))} · HEAD "
        f"<code>{html.escape(str(summary.get('head') or ''))}</code></p>"
        f"<section class='hero'><p class='status {status_class}'>STATUT : {html.escape(status)}</p>"
        "<p class='answer'><b>Meilleure stratégie prouvée :</b> NON</p>"
        "<p><b>Profit comparable mesuré :</b> NON MESURÉ</p>"
        f"<p><b>Objectif configuré :</b> {html.escape(str(economic.get('configured_daily_profit_lock_usd')))} USD/jour "
        "— objectif, pas résultat.</p>"
        f"<p><b>Notionnels :</b> cœur {html.escape(str(economic.get('core_notional_usd')))} USD · "
        f"sonde {html.escape(str(economic.get('probe_notional_usd')))} USD</p></section>"
        "<h2>Ce que le labo a fait</h2><ul>"
        "<li>Vérification du moteur CopyVault et de ses limites PAPER.</li>"
        "<li>Contrôle de la compatibilité replay/backtest et du freeze local.</li>"
        "<li>Aucun ordre réel, aucune collecte et aucun téléchargement.</li>"
        "<li>Ce run ne cherche pas de nouveaux paramètres rentables : il valide le logiciel.</li>"
        "</ul><h2>Détail des contrôles</h2>"
        f"<section class='grid'>{''.join(cards) or '<p>Aucun test lancé.</p>'}</section>"
        f"<h2>Verdict du freeze</h2><p>{html.escape(str(summary.get('freeze_verdict') or ''))}</p>"
        "</main></body></html>"
    )
    _atomic_text(target, page)
    return target


def _open_report(path: Path) -> None:
    if os.environ.get("ALINA_QUANT_NO_OPEN") == "1" or os.name != "nt":
        return
    with suppress(OSError):
        os.startfile(path)  # type: ignore[attr-defined]


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


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
        message = "ÉCHEC FAIL-CLOSED : aucun test trouvé pour ce groupe obligatoire."
        print(message, flush=True)
        log_path.write_text(message + "\n", encoding="utf-8")
        return {
            "name": name,
            "status": "FAIL",
            "return_code": 4,
            "counts": _pytest_counts(""),
            "seconds": 0.0,
            "cpu_seconds": None,
            "peak_working_set_bytes": None,
            "log": str(log_path),
        }

    command = [
        sys.executable, "-m", "pytest", "-vv", "-ra",
        *_pytest_parallel_args(len(tests)), *tests,
    ]
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
                [
                    str(ROOT / "src"),
                    str(ROOT),
                    str(ROOT / "tools"),
                    os.environ.get("PYTHONPATH", ""),
                ]
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
    last_cpu_seconds: float | None = None
    output_lines: list[str] = []
    assert process.stdout is not None
    interrupted = False
    try:
        for line in process.stdout:
            print(line, end="", flush=True)
            output_lines.append(line)
            working_set, cpu_seconds = _windows_process_metrics(process.pid)
            if working_set is not None:
                peak_working_set = max(peak_working_set, working_set)
            if cpu_seconds is not None:
                last_cpu_seconds = cpu_seconds
    except KeyboardInterrupt:
        interrupted = True
        marker = "\n[INTERRUPTED] Ctrl+C reçu; arrêt du groupe de tests et finalisation du rapport.\n"
        print(marker, flush=True)
        output_lines.append(marker)
        _terminate_test_process_tree(process)
    return_code = 130 if interrupted else process.wait()
    elapsed = time.perf_counter() - started
    _, final_cpu_seconds = _windows_process_metrics(process.pid)
    cpu_seconds = (
        final_cpu_seconds if final_cpu_seconds is not None else last_cpu_seconds
    )
    full_output = "".join(output_lines)
    log_path.write_text(full_output, encoding="utf-8")
    counts = _pytest_counts(full_output)
    status = "INTERRUPTED" if interrupted else ("PASS" if return_code == 0 else "FAIL")
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
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ")
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
    safe = inspect_local_safe_corpus(ROOT)
    print(
        "ALINASYNC SAFE : " + str(safe["status"])
        + " | registre shards=" + str(safe["safe_registry_rows"])
        + " | catalogue restauration=" + str(safe.get("restore_catalog_sha256"))
        + " | catalogue actif=" + str(safe.get("active_catalog_sha256"))
        + " | liaison avec les campagnes non prouvee",
        flush=True,
    )
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
        test_groups = _test_groups()
        for index, (name, tests) in enumerate(test_groups, start=1):
            print(
                f"\nPROGRESSION GLOBALE : étape {index}/{len(test_groups)}",
                flush=True,
            )
            groups.append(
                _run_group(name, tests, report_dir / f"etape-{index}.log")
            )
    else:
        print("\nMode pré-vérification : les tests n'ont pas été lancés.", flush=True)

    failures = [row for row in groups if row["status"] == "FAIL"]
    interruptions = [row for row in groups if row["status"] == "INTERRUPTED"]
    economic_result = {
        "comparison_performed": False,
        "best_strategy_proven": False,
        "measured_profit_usd": None,
        "reason": "SOFTWARE_AND_FREEZE_AUDIT_ONLY_NO_ECONOMIC_BACKTEST",
        "configured_daily_profit_lock_usd": freeze.get(
            "configured_daily_profit_lock_usd"
        ),
        "core_notional_usd": freeze.get("core_notional_usd"),
        "probe_notional_usd": freeze.get("probe_notional_usd"),
    }
    overall_status = (
        "INTERRUPTED" if interruptions else
        ("FAIL" if failures else ("PREFLIGHT_ONLY" if preflight_only else "PASS"))
    )
    summary = {
        "run_id": run_id,
        "head": head,
        "paper_read_only": True,
        "network_or_collection_started": False,
        "freeze": freeze,
        "freeze_verdict": freeze_verdict,
        "restore_processes_detected": restore_processes,
        "test_groups": groups,
        "economic_result": economic_result,
        "status": overall_status,
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
        "## Résumé simple",
        "",
        "- Ce labo vérifie le moteur CopyVault, ses limites PAPER, la compatibilité replay et le freeze local.",
        "- Il ne recherche pas encore une nouvelle stratégie et ne réalise pas ici de backtest économique complet.",
        "- Meilleure stratégie prouvée : **NON**.",
        "- Profit mesuré comparable : **NON MESURÉ**.",
        f"- Objectif configuré : **{economic_result['configured_daily_profit_lock_usd']} USD/jour** (paramètre, pas résultat).",
        f"- Notionnel configuré : cœur **{economic_result['core_notional_usd']} USD**, sonde **{economic_result['probe_notional_usd']} USD**.",
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
    html_report = _write_html_report(report_dir, summary)
    print(f"\nRAPPORT DÉTAILLÉ : {report_dir / 'RAPPORT.md'}", flush=True)
    print(f"RÉSULTAT JSON : {report_dir / 'resultat.json'}", flush=True)
    print(f"INTERFACE : {html_report}", flush=True)
    if preflight_only:
        final_verdict = "pré-vérification terminée; les tests n'ont pas été lancés."
    elif interruptions:
        final_verdict = "interrompu proprement; rapport complet écrit, aucun faux succès."
    elif failures:
        final_verdict = "ÉCHEC TESTS — consulter les journaux."
    else:
        final_verdict = "tests exécutés sans échec."
    print("VERDICT FINAL : " + final_verdict, flush=True)
    _open_report(html_report)
    if interruptions:
        return 130
    return 1 if failures else 0




# Legacy local research (Codex/Claude): isolated opt-in, never the default SAFE path.
OBJECTIVE_USD_PER_DAY = 5.0  # dashboard placeholder; replaced from optional module on execution
PAPER_CAPITAL_USD = 1000.0   # never a trading instruction
REASON_LABELS = {
    "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS": (
        "aucun carnet L2 observé n'est disponible au moment du signal (ou dans les 30 secondes avant)"
    ),
    "NO_TRAIN_CANDIDATE_PASSED_GATES": "aucun candidat TRAIN n'a passé les contrôles économiques",
    "INSUFFICIENT_TEMPORAL_REPLAY_INPUTS": "pas assez de données temporelles pour séparer TRAIN, validation, OOS et forward",
    "FILLS_OR_L2_MISSING": "les fills leader ou les carnets L2 vérifiés manquent",
    "COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED": (
        "le réglage actuellement gelé dépasse la limite de 200 USD de capital paper"
    ),
}


def _human_reason(reason: object) -> str:
    raw = str(reason or "tous les contrôles sont passés")
    return REASON_LABELS.get(raw, raw.replace("_", " ").lower())


def _search_space_label() -> str:
    size = 181 * 9_901 * 2_001 * 2_901 * 3_901 * 115_001 * 57 * 5 * 3 * 3 * 46
    return f"{size:,} combinaisons"

def _write_economic_html_report(report_dir: Path, summary: dict[str, Any]) -> Path:
    """Write a plain-French dashboard from the exact machine-readable result."""
    economic = dict(summary.get("economic_result") or {})
    current = dict(summary.get("current_copy_vault") or {})
    historical = dict(summary.get("historical_replay") or {})
    history = list(summary.get("improvement_history") or [])
    inputs = dict(summary.get("safe_inputs") or {})
    continuous = dict(economic.get("continuous_progress") or {})
    temporal_design = dict(economic.get("temporal_design") or {})
    train_result = dict(economic.get("train") or {})
    train_diagnostics = dict(
        continuous.get("best_train_diagnostics")
        or train_result.get("diagnostics")
        or economic.get("train_diagnostics")
        or {}
    )
    partial_fill_diagnostic = dict(
        continuous.get("partial_fill_diagnostic")
        or train_result.get("partial_fill_diagnostic")
        or economic.get("partial_fill_diagnostic")
        or {}
    )
    status = str(summary.get("status") or "UNKNOWN")
    is_running = status == "RUNNING"
    status_class = "ok" if status == "PROVEN" else ("warn" if status in {"RUNNING", "PROMISING", "MORE_DATA", "UNMEASURABLE", "PREFLIGHT_ONLY", "INTERRUPTED"} else "bad")
    def value(source: Mapping[str, Any], segment: str) -> float | None:
        row = source.get(segment) if isinstance(source.get(segment), dict) else {}
        value = row.get("daily_mean_net_pnl_usd")
        return None if value is None else float(value)
    def display(number: float | None) -> str:
        return "non mesurable" if number is None else f"{number:+.4f} USD/jour"
    def total_display(number: object) -> str:
        return "non mesurable" if number is None else f"{float(number):+.6f} USD total TRAIN"
    def train_total(source: Mapping[str, Any]) -> float | None:
        row = source.get("train") if isinstance(source.get("train"), Mapping) else {}
        statistics_row = row.get("statistics") if isinstance(row.get("statistics"), Mapping) else {}
        raw = statistics_row.get("net_pnl_usd")
        return None if raw is None else float(raw)
    def latest(source: Mapping[str, Any]) -> float | None:
        for segment in ("forward", "oos", "validation", "train"):
            measured = value(source, segment)
            if measured is not None:
                return measured
        return None
    current_daily = latest(current)
    current_approximation = (
        dict(current.get("approximation"))
        if isinstance(current.get("approximation"), Mapping) else {}
    )
    approximate_daily = current_approximation.get("daily_net_usd")
    current_display_daily = (
        current_daily if current_daily is not None
        else float(approximate_daily) if approximate_daily is not None else None
    )
    candidate_daily = latest(economic)
    current_train_total = train_total(current)
    candidate_train_total = train_total(economic)
    if candidate_train_total is None:
        candidate_train_total = continuous.get("best_train_net_total_usd")
    current_train_daily = value(current, "train")
    candidate_train_daily = value(economic, "train")
    if candidate_train_daily is None and continuous.get("best_train_score_metric") == "daily_mean_net_pnl_usd":
        candidate_train_daily = continuous.get("best_train_score")
    comparable_segment = None
    comparable_delta = None
    for segment in ("forward", "oos", "validation", "train"):
        baseline_value = value(current, segment)
        candidate_value = value(economic, segment)
        if baseline_value is not None and candidate_value is not None:
            comparable_segment = segment
            comparable_delta = candidate_value - baseline_value
            break
    train_delta = (
        float(candidate_train_total) - current_train_total
        if candidate_train_total is not None and current_train_total is not None else None
    )
    train_daily_delta = (
        float(candidate_train_daily) - current_train_daily
        if candidate_train_daily is not None and current_train_daily is not None else None
    )
    historical_best = (
        dict(historical.get("best_candidate"))
        if isinstance(historical.get("best_candidate"), Mapping) else {}
    )
    historical_baseline = (
        dict(historical.get("baseline"))
        if isinstance(historical.get("baseline"), Mapping) else {}
    )
    candidate_is_historical = False
    if candidate_daily is None and historical_best.get("daily_net_pnl_usd") is not None:
        candidate_daily = float(historical_best["daily_net_pnl_usd"])
        candidate_is_historical = True
    improvement = (
        candidate_daily - current_daily
        if candidate_daily is not None and current_daily is not None else None
    )
    if improvement is None and historical.get("improvement_usd_per_day") is not None:
        improvement = float(historical["improvement_usd_per_day"])
    history_rows = []
    for row in reversed(history[-20:]):
        history_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('run_id') or ''))}</td>"
            f"<td>{html.escape(str(row.get('classification') or ''))}</td>"
            f"<td>{display(row.get('baseline_daily_net_usd'))}</td>"
            f"<td>{display(row.get('candidate_daily_net_usd'))}"
            f"{'' if row.get('candidate_daily_net_usd') is not None else ('<br>' + total_display(row.get('candidate_train_net_total_usd')) if row.get('candidate_train_net_total_usd') is not None else '')}</td>"
            f"<td>{display(row.get('improvement_usd_per_day'))}"
            f"{'' if row.get('improvement_usd_per_day') is not None else ('<br>' + (total_display(row.get('selection_score')) if row.get('selection_score_metric') == 'net_pnl_usd' else display(row.get('selection_score'))) if row.get('selection_score') is not None else '')}</td>"
            f"<td><code>{html.escape(str(row.get('input_sha256') or ''))[:16]}</code></td>"
            f"<td><code>{html.escape(str(row.get('engine_sha256') or ''))[:16]}</code></td>"
            f"<td>{'OUI' if row.get('economically_proven') is True else 'NON'}</td>"
            "</tr>"
        )
    train_improvement_rows = []
    train_improvements = list(economic.get("train_improvements") or [])
    for row in train_improvements:
        train = dict(row.get("train") or {})
        statistics_row = dict(train.get("statistics") or {})
        candidate = dict(row.get("candidate") or {})
        freeze = dict(candidate.get("freeze") or {})
        parameters = dict(freeze.get("parameters") or {})
        total_net = statistics_row.get("net_pnl_usd")
        sample_count = int(statistics_row.get("sample_count") or 0)
        exposure = (
            float(parameters.get("core_notional_usd") or 0.0)
            + float(parameters.get("probe_notional_usd") or 0.0)
        )
        train_improvement_rows.append(
            "<tr>"
            f"<td>{int(row.get('trial') or 0)}</td>"
            f"<td>{sample_count}</td>"
            f"<td>{'non mesurable' if total_net is None else f'{float(total_net):+.6f} USD'}</td>"
            f"<td>{float(parameters.get('horizon_ms') or 0.0) / 1000:.0f} s</td>"
            f"<td>{exposure:.0f} USD</td>"
            "<td>NON</td></tr>"
        )
    proven = economic.get("economically_proven") is True
    exploratory_freezes = int(economic.get("exploratory_freezes_created") or 0)
    frozen = (
        economic.get("freeze_created") is True
        or exploratory_freezes > 0
        or historical.get("improvement_found") is True
    )
    target = report_dir / "RAPPORT.html"
    page = (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Laboratoire CopyVault</title>"
        + ("<meta http-equiv='refresh' content='2'>" if is_running else "")
        + "<style>"
        ":root{color-scheme:dark}body{font:16px system-ui;margin:0;background:#09111f;color:#e7edf7}"
        "main{max-width:1050px;margin:auto;padding:32px}h1{margin-bottom:6px}.muted{color:#9fb0c8}"
        ".hero,.card{background:#111d30;border:1px solid #29405f;border-radius:14px;padding:20px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0}"
        ".status{font-weight:800;font-size:1.15rem}.ok{color:#54e38e}.warn{color:#ffd166}.bad{color:#ff6b7a}"
        ".answer{font-size:1.25rem}.path{overflow-wrap:anywhere;color:#9fb0c8}"
        "code{color:#8fd3ff}li{margin:.5rem 0}table{width:100%;border-collapse:collapse}"
        "th,td{text-align:left;padding:9px;border-bottom:1px solid #29405f}</style></head><body><main>"
        "<h1>Laboratoire CopyVault</h1>"
        f"<p class='muted'>Run {html.escape(str(summary.get('run_id') or ''))} · HEAD "
        f"<code>{html.escape(str(summary.get('head') or ''))}</code></p>"
        f"<section class='hero'><p class='status {status_class}'>VERDICT : {html.escape(status)}</p>"
        f"<p class='answer'><b>Stratégie économiquement prouvée :</b> {'OUI' if proven else 'NON'}</p>"
        f"<p><b>Candidat gelé pour comparaison suivante :</b> {'OUI' if frozen else 'NON'}</p>"
        f"<p><b>Améliorations successives TRAIN conservées :</b> {exploratory_freezes}</p>"
        f"<p><b>Objectif :</b> {OBJECTIVE_USD_PER_DAY:.2f} USD nets/jour avec {PAPER_CAPITAL_USD:.0f} USD paper.</p>"
        f"<p><b>Découpage temporel :</b> TRAIN → VALIDATION → OOS → FORWARD; purge de {int(temporal_design.get('purge_ms') or 0):,} ms autour des frontières; held-out non consultés pendant le réglage.</p>"
        f"<p><b>Pourquoi :</b> {html.escape(_human_reason(economic.get('reason')))}</p></section>"
        + (
            "<section class='card'><h2>Recherche en direct</h2>"
            f"<p class='answer'><b>Essais terminés :</b> {int(continuous.get('next_sequence_index') or 0):,} "
            f"(compteur statistique global : {int(continuous.get('cumulative_trial_count') or 0):,})</p>"
            f"<p><b>En cours :</b> {html.escape(str(continuous.get('phase') or 'initialisation'))}</p>"
            f"<p><b>Dernier essai TRAIN :</b> {html.escape(str(continuous.get('last_trial_text') or 'en attente'))}</p>"
            f"<p><b>Meilleure mesure TRAIN selon l'échantillon :</b> {html.escape(str(continuous.get('best_train_text') or 'non mesurable'))}</p>"
            f"<p><b>Candidat en cours :</b> {html.escape(str(continuous.get('current_candidate_id') or 'préparation'))}</p>"
            f"<p><b>Réglages du replay :</b> {html.escape(str(continuous.get('parameter_summary') or 'en préparation'))}</p>"
            f"<p><b>Recherche :</b> {html.escape(str(continuous.get('search_method') or '4 essais globaux puis 1 raffinement local'))}; espace global borné d'environ {_search_space_label()}</p>"
            f"<p><b>Robustesse locale du meilleur :</b> {int(continuous.get('neighbor_positive_count') or 0)}/{int(continuous.get('neighbor_count') or 0)} variantes TRAIN positives; diagnostic exploratoire.</p>"
            f"<p><b>Risque TRAIN :</b> drawdown max {html.escape(str(train_diagnostics.get('max_drawdown_usd', 'non mesurable')))} USD; facteur de profit {html.escape(str(train_diagnostics.get('profit_factor', 'non mesurable')))}; borne basse par jour actif {html.escape(str(train_diagnostics.get('daily_mean_lcb_usd', 'non mesurable')))} USD.</p>"
            f"<p><b>Dispersion :</b> écart-type net/trade {html.escape(str(train_diagnostics.get('trade_net_stddev_usd', 'non mesurable')))} USD; écart-type/jour actif {html.escape(str(train_diagnostics.get('active_day_net_stddev_usd', 'non mesurable')))} USD.</p>"
            f"<p><b>Coûts du dernier replay :</b> {html.escape(str((continuous.get('last_train_diagnostics') or train_diagnostics).get('costs') or 'non mesurables'))}</p>"
            f"<details><summary>Résultats TRAIN par vault leader, actif et régime</summary><pre>{html.escape(json.dumps(train_diagnostics.get('slices') or {}, ensure_ascii=False, indent=2))}</pre></details>"
            f"<p><b>Fill partiel exploratoire :</b> {html.escape(str(partial_fill_diagnostic.get('partial_fill_trade_count', 'non mesurable')))} exécution(s) partielle(s) simulée(s) sur L2 observé; priorité de file inconnue, résultat non certifiant.</p>"
            "<p class='muted'>Le score principal garde les exécutions complètes exigées par le replay V21. Un diagnostic distinct réduit la taille au volume commun visible sur les deux jambes, sans inventer de fill ni de rang de file. La recherche reste sur TRAIN. Validation, OOS et FORWARD sont affichés séparément et ne servent pas au réglage. Le classement par PnL total n'est pas un rendement journalier. Ctrl+C sauvegarde l'essai terminé.</p></section>"
            if is_running or continuous else ""
        )
        + "<h2>Comparaison avec le Copy‑Vault actuel</h2><section class='grid'>"
        f"<article class='card'><h3>Copy‑Vault actuel</h3><p class='answer'>{'≈ ' if current_daily is None and current_display_daily is not None else ''}{display(current_display_daily)}</p>"
        f"<p>Replay TRAIN sur mêmes événements : {total_display(current_train_total)}</p>"
        f"<p class='muted'>{html.escape(str(current.get('status') or 'NON MESURÉ'))} — {html.escape(_human_reason(current.get('reason')))}</p></article>"
        f"<article class='card'><h3>Meilleur candidat</h3><p class='answer'>{display(candidate_daily) if candidate_daily is not None else html.escape(str(continuous.get('best_train_text') or total_display(candidate_train_total)))}</p>"
        f"<p>Replay TRAIN : {total_display(candidate_train_total)}</p>"
        f"<p class='muted'>{html.escape(str((historical.get('status') if candidate_is_historical else economic.get('status')) or 'NON MESURÉ'))}</p></article>"
        f"<article class='card'><h3>Écart mesuré sur un même segment</h3><p class='answer'>{display(comparable_delta) if comparable_delta is not None else (total_display(train_delta) if train_delta is not None else 'non mesurable')}</p>"
        f"<p class='muted'>{('Segment ' + comparable_segment.upper() + ', calculé sur la même partition SAFE; indicatif et non utilisé pour régler le candidat.') if comparable_segment else ('Écart du total TRAIN sur les mêmes événements SAFE.' if train_delta is not None else 'Pas de métriques comparables sur un même segment.')}</p></article></section>"
        + (
            "<p class='muted'>Estimation actuelle fondée sur le dernier TRAIN V21 : "
            f"environ {display(current_display_daily)}, borne statistique conservatrice "
            f"{display(float(current_approximation['conservative_lcb_usd_per_day']))}, "
            f"sur {int(current_approximation.get('sample_count') or 0)} trades / "
            f"{int(current_approximation.get('distinct_days') or 0)} jours. "
            "C'est un ordre de grandeur redimensionné à 200 USD, pas une preuve OOS/forward.</p>"
            if current_approximation else ""
        )
        +
        "<h2>Replay historique de secours (séparé des données SAFE)</h2>"
        f"<p><b>{int(historical.get('trial_count') or 0)} scénarios</b> recalculés sur "
        f"<b>{int(historical.get('source_trade_count') or 0)} trades exécutables</b> conservés. "
        f"La recherche couvre {int(historical.get('unique_filter_count') or 0)} sous-ensembles distincts "
        f"issus de {int(historical.get('mechanism_count') or 0)} mécanismes. "
        f"Baseline comparable : {display(historical_baseline.get('daily_net_pnl_usd'))}; "
        f"meilleur candidat : {display(historical_best.get('daily_net_pnl_usd'))}; "
        f"écart : {display(historical.get('improvement_usd_per_day'))}. "
        "Résultat exploratoire TRAIN, conservé mais jamais présenté comme preuve OOS/forward.</p>"
        "<h2>Walk-forward chronologique et résultats séparés</h2>"
        f"<p class='muted'>VALIDATION : {html.escape(str((economic.get('validation') or {}).get('status') or 'non évaluée'))}; "
        f"OOS : {html.escape(str((economic.get('oos') or {}).get('status') or 'non évalué'))}; "
        f"FORWARD : {html.escape(str((economic.get('forward') or {}).get('status') or 'non évalué'))}. "
        "L’étape suivante ne s’ouvre qu’après le passage de la précédente.</p>"
        "<section class='grid'>"
        f"<article class='card'><h3>TRAIN candidat</h3><p>{display(value(economic, 'train'))}</p></article>"
        f"<article class='card'><h3>VALIDATION</h3><p>actuel {display(value(current, 'validation'))}<br>candidat {display(value(economic, 'validation'))}</p></article>"
        f"<article class='card'><h3>OOS</h3><p>actuel {display(value(current, 'oos'))}<br>candidat {display(value(economic, 'oos'))}</p></article>"
        f"<article class='card'><h3>FORWARD</h3><p>actuel {display(value(current, 'forward'))}<br>candidat {display(value(economic, 'forward'))}</p></article></section>"
        "<h2>Meilleurs successifs observés sur TRAIN</h2>"
        + (
            "<p class='muted'>Ces lignes sont gelées pour comparaison future. Un total négatif reste une perte; "
            "aucune ligne n'est une preuve de rentabilité.</p>"
            "<table><thead><tr><th>Essai</th><th>Trades</th><th>Net TRAIN total</th><th>Horizon</th><th>Capital</th><th>Prouvé</th></tr></thead>"
            f"<tbody>{''.join(train_improvement_rows)}</tbody></table>"
            if train_improvement_rows else "<p>Aucun score TRAIN exploitable n'a été obtenu.</p>"
        )
        +
        "<h2>Historique conservé des améliorations</h2>"
        + (
            "<table><thead><tr><th>Run</th><th>État</th><th>Avant</th><th>Candidat</th><th>Gain</th><th>Hash données</th><th>Hash moteur</th><th>Prouvé</th></tr></thead>"
            f"<tbody>{''.join(history_rows)}</tbody></table>"
            if history_rows else "<p>Aucun candidat amélioré n'a encore pu être mesuré et gelé.</p>"
        )
        +
        "<h2>Ce que ce run a réellement fait</h2><ul>"
        f"<li>{int(inputs.get('verified_assets') or 0)} fichiers Copy‑Vault vérifiés à nouveau par taille et SHA‑256.</li>"
        f"<li>{int(inputs.get('unique_fills') or 0)} fills leader uniques et {int(inputs.get('unique_books') or 0)} carnets L2 uniques reconstruits.</li>"
        f"<li>Dans ces fills : {int(inputs.get('historical_train_fills') or 0)} historiques réservés à TRAIN et {int(inputs.get('forward_fills', inputs.get('unique_fills') or 0))} observations prospectives vérifiables.</li>"
        f"<li>Catalogue SAFE utilisé : {html.escape(str(inputs.get('catalog_sha256') or 'non renseigné'))}; empreinte du corpus : {html.escape(str(inputs.get('selection_digest') or 'non renseignée'))}; octets décompressés : {int(inputs.get('selected_raw_bytes') or 0):,}.</li>"
        f"<li>{int(economic.get('candidates_tested') or 0) + int(historical.get('trial_count') or 0)} configurations réellement rejouées, coûts et liquidité observée inclus.</li>"
        "<li>Recherche sur TRAIN uniquement; VALIDATION, OOS et FORWARD ne servent jamais au réglage.</li>"
        "<li>L'historique REST peut enrichir TRAIN; seules les entrées live causales ou REST exactes non historiques alimentent les segments held-out.</li>"
        "<li>Aucune collecte réseau, aucun ordre, aucune clé et aucune transaction.</li></ul>"
        f"<h2>Verdict simple</h2><p>{html.escape(str(summary.get('freeze_verdict') or ''))}</p>"
        f"<p class='path'>Données machine : {html.escape(str(report_dir / 'resultat.json'))}</p>"
        "</main></body></html>"
    )
    _atomic_text(target, page)
    return target


def _prior_trial_pressure(root: Path) -> tuple[int, dict[str, Any]]:
    """Conservatively account for discovery-ledger and prior local replay trials."""
    context: dict[str, Any] = {}
    command = [sys.executable, str(root / "tools" / "codex_research_context.py"), "--auto"]
    try:
        completed = subprocess.run(
            command, cwd=root, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )
        if completed.returncode == 0:
            context = json.loads(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        context = {}
    ledger_trials = int(
        (context.get("trial_accounting") or {}).get("ledger_trials")
        or (context.get("ledger") or {}).get("trial_count")
        or 0
    )
    report_trials = 0
    reports = root / "runtime" / "reports" / "copy_vault_quant_lab"
    if reports.is_dir():
        for result_path in reports.glob("*/resultat.json"):
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                economic = result.get("economic_result") or {}
                historical = result.get("historical_replay") or {}
                report_trials += int(economic.get("candidates_tested") or 0)
                report_trials += int(historical.get("trial_count") or 0)
            except (OSError, ValueError, TypeError):
                continue
    # Summing independent ledgers intentionally overcounts possible overlap rather
    # than understating the multiple-testing burden.
    return ledger_trials + report_trials, {
        "hypothesis_ledger_trials": ledger_trials,
        "prior_local_report_trials": report_trials,
        "accounting_policy": "CONSERVATIVE_SUM_POSSIBLE_OVERLAP",
        "research_context_available": bool(context),
    }


def run_economic_lab(
    *,
    preflight_only: bool = False,
    tests_only: bool = False,
    dataset_root: Path | None = None,
    supplied_safe_inputs: Mapping[str, Any] | None = None,
    continuous: bool = False,
) -> int:
    # Imported only for explicit local legacy economic runs. A clean GitHub
    # clone can lack this optional Codex/Claude module: fail closed, do not
    # substitute fake fills, synthetic books or pretend to have proven profit.
    try:
        from hl_observer.backtesting.copy_vault_local_lab import (
            OBJECTIVE_USD_PER_DAY as _objective,
            PAPER_CAPITAL_USD as _capital,
            evaluate_current_copy_vault,
            load_improvement_history,
            materialize_safe_workspace,
            record_frozen_candidate,
            run_historical_trade_replay,
            run_local_campaign,
        )
    except ImportError as exc:
        print('LOCAL_ECONOMIC_NO_GO: missing optional local Copy-Vault module: ' + str(exc), flush=True)
        return 2
    global OBJECTIVE_USD_PER_DAY, PAPER_CAPITAL_USD
    OBJECTIVE_USD_PER_DAY, PAPER_CAPITAL_USD = _objective, _capital
    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ")
    report_dir = ROOT / "runtime" / "reports" / "copy_vault_quant_lab" / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    head_run = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    head = head_run.stdout.strip() if head_run.returncode == 0 else "INCONNU"
    print("ALINA SMART FLOW — VRAI LABORATOIRE REPLAY / BACKTEST COPY-VAULT", flush=True)
    print("PAPER / READ-ONLY : données locales uniquement, aucun ordre ni téléchargement.", flush=True)
    print(f"Dépôt : {ROOT}\nHEAD : {head}", flush=True)
    groups: list[dict[str, Any]] = []
    safe_inputs: dict[str, Any] = {}
    economic_result: dict[str, Any] = {}
    current_copy_vault: dict[str, Any] = {}
    historical_replay: dict[str, Any] = {}
    interrupted = False
    live_opened = False
    continuous_progress: dict[str, Any] = {}
    last_trial: dict[str, Any] = {}
    exploratory_freeze_count = 0
    if tests_only:
        test_groups = _test_groups()
        for index, (name, tests) in enumerate(test_groups, start=1):
            print(
                f"\nPROGRESSION GLOBALE : étape {index}/{len(test_groups)}",
                flush=True,
            )
            groups.append(
                _run_group(name, tests, report_dir / f"etape-{index}.log")
            )
        interruptions = [row for row in groups if row["status"] == "INTERRUPTED"]
        failures = [row for row in groups if row["status"] == "FAIL"]
        interrupted = bool(interruptions)
        overall_status = "INTERRUPTED" if interrupted else ("FAIL" if failures else "PASS")
        economic_result = {
            "status": "NOT_RUN_TESTS_ONLY", "reason": "TESTS_ONLY_NO_ECONOMIC_BACKTEST",
            "candidates_tested": 0, "freeze_created": False, "economically_proven": False,
        }
    else:
        recovery = ROOT / "runtime" / "recovery" / "full"
        workspace = Path(dataset_root).resolve() if dataset_root is not None else report_dir / "workspace"
        print("\n[1/4] Vérification SAFE : taille + SHA-256 de chaque shard Copy-Vault...", flush=True)
        if dataset_root is None:
            safe_inputs = materialize_safe_workspace(recovery, workspace)
        else:
            supplied = dict(supplied_safe_inputs or {})
            counts = dict(supplied.get("counts") or {})
            safe_inputs = {
                "status": "READY",
                "reason": None,
                "verified_assets": int(supplied.get("selected_shards") or 0),
                "unique_fills": (
                    int(counts.get("copy_vault_fills") or 0)
                    + int(counts.get("copy_vault_snapshot") or 0)
                ),
                "forward_fills": int(counts.get("copy_vault_fills") or 0),
                "historical_train_fills": int(counts.get("copy_vault_snapshot") or 0),
                "unique_books": int(counts.get("copy_vault_l2") or 0),
                "catalog_sha256": supplied.get("catalog_sha256"),
                "selection_digest": supplied.get("selection_digest"),
                "selected_raw_bytes": supplied.get("selected_raw_bytes"),
                "workspace": str(workspace),
                "source": "ALINASYNC_CURRENT_SAFE_CATALOG",
                "paper_read_only": True,
                "real_execution": False,
            }
        print(
            f"      {safe_inputs.get('verified_assets', 0)} fichiers vérifiés; "
            f"{safe_inputs.get('unique_fills', 0)} fills au total "
            f"({safe_inputs.get('historical_train_fills', 0)} historiques TRAIN, "
            f"{safe_inputs.get('forward_fills', safe_inputs.get('unique_fills', 0))} prospectifs); "
            f"{safe_inputs.get('unique_books', 0)} carnets L2.",
            flush=True,
        )
        if preflight_only:
            overall_status = "PREFLIGHT_ONLY"
            economic_result = {
                "status": "NOT_RUN_PREFLIGHT_ONLY", "reason": safe_inputs.get("reason"),
                "candidates_tested": 0, "freeze_created": False, "economically_proven": False,
            }
        elif safe_inputs.get("status") != "READY":
            overall_status = "UNMEASURABLE"
            economic_result = {
                "status": "UNMEASURABLE", "reason": safe_inputs.get("reason"),
                "candidates_tested": 0, "freeze_created": False, "economically_proven": False,
            }
        else:
            print("[2/4] Reconstruction des épisodes et des signaux leader...", flush=True)
            current_copy_vault = evaluate_current_copy_vault(
                workspace,
                ROOT / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json",
            )
            print(
                "      Copy-Vault actuel : "
                + str(current_copy_vault.get("status") or "UNMEASURABLE")
                + " — "
                + _human_reason(current_copy_vault.get("reason")),
                flush=True,
            )
            prior_trial_count = 0
            trial_accounting: dict[str, Any] = {}
            if continuous:
                prior_trial_count, trial_accounting = _prior_trial_pressure(ROOT)
                print(
                    f"[3/4] Recherche continue TRAIN — {prior_trial_count:,} essais antérieurs "
                    "comptabilisés pour corriger la sélection multiple.",
                    flush=True,
                )
                continuous_progress = {
                    "phase": "préparation du replay TRAIN",
                    "next_sequence_index": 0,
                    "cumulative_trial_count": prior_trial_count,
                    "best_train_text": "non mesurable",
                    "trial_accounting": trial_accounting,
                }
                economic_result = {
                    "status": "RUNNING",
                    "reason": "CONTINUOUS_TRAIN_SEARCH",
                    "continuous": True,
                    "continuous_progress": continuous_progress,
                    "candidates_tested": 0,
                    "freeze_created": False,
                    "economically_proven": False,
                    "heldout_status": "PROTECTED_NOT_USED_DURING_CONTINUOUS_TUNING",
                    "trial_accounting": trial_accounting,
                }
                live_summary = {
                    "run_id": run_id, "head": head, "status": "RUNNING",
                    "paper_read_only": True, "network_or_collection_started": False,
                    "safe_inputs": safe_inputs, "current_copy_vault": current_copy_vault,
                    "historical_replay": historical_replay,
                    "improvement_history": load_improvement_history(ROOT),
                    "economic_result": economic_result,
                    "freeze_verdict": "Recherche TRAIN continue en cours; aucune preuve économique n'est déclarée.",
                }
                html_report = _write_economic_html_report(report_dir, live_summary)
                _atomic_text(
                    report_dir / "resultat.json",
                    json.dumps(live_summary, ensure_ascii=False, indent=2) + "\n",
                )
                _open_report(html_report)
                live_opened = True
                print(f"INTERFACE EN DIRECT : {html_report}", flush=True)

                # Run the existing independent historical trade replay once; its
                # stress results remain separately classified as exploratory.
                continuous_progress["phase"] = "replay historique exploratoire"
                live_summary["economic_result"] = economic_result
                _atomic_text(
                    report_dir / "resultat.json",
                    json.dumps(live_summary, ensure_ascii=False, indent=2) + "\n",
                )
                _write_economic_html_report(report_dir, live_summary)
                try:
                    def historical_progress(message: str) -> None:
                        print(f"[4/4] {message}", flush=True)
                        continuous_progress["phase"] = "replay historique TRAIN : " + str(message)
                        economic_result["continuous_progress"] = dict(continuous_progress)
                        live_summary["economic_result"] = economic_result
                        _atomic_text(
                            report_dir / "resultat.json",
                            json.dumps(live_summary, ensure_ascii=False, indent=2) + "\n",
                        )
                        _write_economic_html_report(report_dir, live_summary)

                    historical_replay = run_historical_trade_replay(
                        ROOT,
                        progress=historical_progress if continuous else (
                            lambda message: print(f"[4/4] {message}", flush=True)
                        ),
                    )
                except KeyboardInterrupt:
                    interrupted = True
                    economic_result = {
                        "status": "INTERRUPTED",
                        "reason": "USER_CTRL_C_DURING_HISTORICAL_REPLAY",
                        "candidates_tested": 0,
                        "freeze_created": False,
                        "economically_proven": False,
                        "continuous": True,
                        "continuous_progress": dict(continuous_progress),
                        "trial_accounting": trial_accounting,
                    }
                    historical_replay = {
                        "status": "INTERRUPTED",
                        "reason": "USER_CTRL_C_DURING_HISTORICAL_REPLAY",
                        "economically_proven": False,
                    }
                if historical_replay.get("improvement_found") is True:
                    best = dict(historical_replay.get("best_candidate") or {})
                    baseline = dict(historical_replay.get("baseline") or {})
                    historical_candidate = {
                        "schema_version": "hypersmart.copy_vault_historical_candidate.v1",
                        "source": historical_replay.get("source"),
                        "configuration": {
                            key: best.get(key) for key in (
                                "filter", "capital_usd", "fee_multiplier",
                                "spread_multiplier", "latency_multiplier",
                                "slippage_multiplier", "mechanism_archetypes",
                            )
                        },
                    }
                    historical_id = "historical-" + hashlib.sha256(
                        json.dumps(historical_candidate, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest()[:20]
                    historical_replay["immutable_history_record"] = record_frozen_candidate(
                        ROOT,
                        historical_id,
                        {
                            "freeze_created": True,
                            "economically_proven": False,
                            "status": "HISTORICAL_TRAIN_CANDIDATE_FROZEN",
                            "selected_candidate": historical_candidate,
                            "train": {"daily_mean_net_pnl_usd": best.get("daily_net_pnl_usd")},
                        },
                        {"train": {"daily_mean_net_pnl_usd": baseline.get("daily_net_pnl_usd")}},
                    )
                historical_trials_this_run = int(historical_replay.get("trial_count") or 0)
                prior_trial_count += historical_trials_this_run
                trial_accounting["historical_trials_this_run"] = historical_trials_this_run
                trial_accounting["cumulative_before_streaming_search"] = prior_trial_count
                continuous_progress.update({
                    "phase": "préparation de la recherche continue TRAIN",
                    "cumulative_trial_count": prior_trial_count,
                    "trial_accounting": trial_accounting,
                })
                economic_result["continuous_progress"] = dict(continuous_progress)
                economic_result["trial_accounting"] = trial_accounting
                live_summary["historical_replay"] = historical_replay
                live_summary["economic_result"] = economic_result
                _atomic_text(
                    report_dir / "resultat.json",
                    json.dumps(live_summary, ensure_ascii=False, indent=2) + "\n",
                )
                _write_economic_html_report(report_dir, live_summary)

                def persist_train_improvement(improvement: Mapping[str, Any]) -> None:
                    nonlocal exploratory_freeze_count
                    candidate = dict(improvement.get("candidate") or {})
                    freeze = dict(candidate.get("freeze") or {})
                    immutable_id = "continuous-v2-" + str(
                        freeze.get("campaign_id") or improvement.get("trial") or "unknown"
                    )
                    record = record_frozen_candidate(
                        ROOT,
                        immutable_id,
                        {
                            "freeze_created": True,
                            "economically_proven": False,
                            "status": "TRAIN_ONLY_EXPLORATORY_IMPROVEMENT",
                            "selected_candidate": improvement.get("candidate"),
                            "train": improvement.get("train"),
                            "selection_score_metric": improvement.get("selection_metric"),
                            "selection_score": improvement.get("selection_score"),
                            "previous_best_train_score": improvement.get("previous_best_score"),
                            "input_sha256": improvement.get("input_sha256"),
                            "engine_sha256": improvement.get("engine_sha256"),
                            "train_diagnostics": improvement.get("train_diagnostics"),
                            "parameter_neighbor_diagnostics": improvement.get("parameter_neighbor_diagnostics") or [],
                            "partial_fill_diagnostic": improvement.get("partial_fill_diagnostic"),
                        },
                        current_copy_vault,
                    )
                    exploratory_freeze_count += int(record is not None)

                last_dashboard_update = 0.0

                def update_live_dashboard(update: Mapping[str, Any]) -> None:
                    nonlocal last_dashboard_update
                    now_mono = time.monotonic()
                    if update.get("phase") == "TRIAL_START":
                        candidate = dict(update.get("candidate") or {})
                        freeze = dict(candidate.get("freeze") or {})
                        params = dict(freeze.get("parameters") or {})
                        gross = float(params.get("core_notional_usd") or 0) + float(params.get("probe_notional_usd") or 0)
                        continuous_progress.update({
                            "phase": "replay TRAIN en cours — signaux, liquidité, frais et sorties",
                            "next_sequence_index": int(update.get("sequence_index") or 0),
                            "cumulative_trial_count": int(update.get("cumulative_trial_count") or prior_trial_count),
                            "current_candidate_id": str(update.get("candidate_id") or ""),
                            "input_sha256": update.get("input_sha256"),
                            "engine_sha256": update.get("engine_sha256"),
                            "selection_score_metric": update.get("selection_score_metric"),
                            "parameter_summary": (
                                f"capital exposé {gross:.2f}/200 USD; cœur {float(params.get('core_notional_usd') or 0):.2f}; "
                                f"sonde {float(params.get('probe_notional_usd') or 0):.2f}; seuil leader "
                                f"{float(params.get('minimum_leader_fill_notional_usd') or 0):.2f}; déséquilibre "
                                f"{float(params.get('signed_depth_imbalance_minimum') or 0):+.3f}; stop/take "
                                f"{float(params.get('stop_loss_bps') or 0):.1f}/{float(params.get('take_profit_bps') or 0):.1f} bps; "
                                f"horizon {int(params.get('horizon_ms') or 0)} ms; limite jour "
                                f"{int(params.get('vault_daily_limit') or 0)}/{int(params.get('coin_daily_limit') or 0)}"
                            ),
                            "trial_accounting": trial_accounting,
                        })
                        if now_mono - last_dashboard_update < 1.5:
                            return
                        last_dashboard_update = now_mono
                        economic_result.update({
                            "status": "RUNNING",
                            "reason": "CONTINUOUS_TRAIN_SEARCH",
                            "continuous_progress": dict(continuous_progress),
                            "candidates_tested": int(update.get("sequence_index") or 0),
                            "cumulative_trial_count": int(update.get("cumulative_trial_count") or 0),
                            "freeze_created": economic_result.get("freeze_created", False),
                            "economically_proven": False,
                            "heldout_status": "PROTECTED_NOT_USED_DURING_CONTINUOUS_TUNING",
                            "trial_accounting": trial_accounting,
                            "paper_read_only": True,
                            "real_execution": False,
                        })
                        live_summary["economic_result"] = economic_result
                        _atomic_text(
                            report_dir / "resultat.json",
                            json.dumps(live_summary, ensure_ascii=False, indent=2) + "\n",
                        )
                        _write_economic_html_report(report_dir, live_summary)
                        return

                    last_trial.clear()
                    last_trial.update(dict(update))
                    improved = update.get("is_improvement") is True
                    if now_mono - last_dashboard_update < 1.5 and not improved:
                        return
                    last_dashboard_update = now_mono
                    score = update.get("best_train_score")
                    score_metric = str(update.get("best_train_score_metric") or "")
                    last_net = update.get("net_train_usd")
                    last_daily = update.get("daily_mean_net_pnl_usd")
                    diagnostics = dict(update.get("train_diagnostics") or {})
                    neighbor_rows = list(update.get("best_parameter_neighbor_diagnostics") or [])
                    neighbor_positive = sum(
                        1 for row in neighbor_rows
                        if isinstance(row, Mapping)
                        and row.get("net_pnl_usd") is not None
                        and float(row["net_pnl_usd"]) > 0.0
                    )
                    continuous_progress.update({
                        "phase": "replay TRAIN / recherche de candidats",
                        "next_sequence_index": int(update.get("next_sequence_index") or 0),
                        "cumulative_trial_count": int(update.get("cumulative_trial_count") or prior_trial_count),
                        "current_candidate_id": str(update.get("candidate_id") or ""),
                        "last_trial_text": (
                            "non mesurable" if last_net is None
                            else (
                                f"{float(last_net):+.6f} USD total TRAIN; "
                                f"{'non mesurable' if last_daily is None else f'{float(last_daily):+.6f} USD/jour'}"
                            )
                        ),
                        "best_train_text": (
                            "non mesurable" if score is None
                            else (
                                f"{float(score):+.6f} USD/jour net TRAIN (exploratoire)"
                                if score_metric == "daily_mean_net_pnl_usd"
                                else f"{float(score):+.6f} USD total TRAIN (fenêtre fixe; journalier non mesurable)"
                            )
                        ),
                        "search_method": update.get("search_method"),
                        "input_sha256": update.get("input_sha256"),
                        "engine_sha256": update.get("engine_sha256"),
                        "last_train_diagnostics": diagnostics,
                        "best_train_diagnostics": update.get("best_train_diagnostics") or {},
                        "neighbor_count": len(neighbor_rows),
                        "neighbor_positive_count": neighbor_positive,
                        "partial_fill_diagnostic": update.get("best_partial_fill_diagnostic"),
                        "trial_accounting": trial_accounting,
                        "state_path": str(update.get("state_path") or ""),
                        "journal_path": str(update.get("journal_path") or ""),
                    })
                    economic_result.update({
                        "status": "RUNNING",
                        "reason": "CONTINUOUS_TRAIN_SEARCH",
                        "continuous_progress": dict(continuous_progress),
                        "candidates_tested": int(update.get("next_sequence_index") or 0),
                        "cumulative_trial_count": int(update.get("cumulative_trial_count") or 0),
                        "best_train_score": score,
                        "best_train_score_metric": score_metric,
                        "best_train_daily_usd": score if score_metric == "daily_mean_net_pnl_usd" else None,
                        "best_train_net_total_usd": update.get("best_train_net_total_usd"),
                        "best_train_diagnostics": update.get("best_train_diagnostics") or {},
                        "selected_candidate": update.get("candidate") if improved else economic_result.get("selected_candidate"),
                        "exploratory_freezes_created": exploratory_freeze_count,
                        "freeze_created": bool(score is not None),
                        "economically_proven": False,
                        "heldout_status": "PROTECTED_NOT_USED_DURING_CONTINUOUS_TUNING",
                        "paper_read_only": True,
                        "real_execution": False,
                    })
                    live_summary["economic_result"] = economic_result
                    live_summary["historical_replay"] = historical_replay
                    live_summary["improvement_history"] = load_improvement_history(ROOT)
                    live_summary["freeze_verdict"] = (
                        "Recherche TRAIN en cours. Les meilleurs scores sont gelés dans l'historique; "
                        "VALIDATION/OOS/FORWARD ne sont pas consultés pendant le réglage."
                    )
                    _atomic_text(
                        report_dir / "resultat.json",
                        json.dumps(live_summary, ensure_ascii=False, indent=2) + "\n",
                    )
                    _write_economic_html_report(report_dir, live_summary)

            if not interrupted:
                try:
                    economic_result = run_local_campaign(
                        workspace,
                        progress=lambda message: print(f"[3/4] {message}", flush=True),
                        continuous=continuous,
                        prior_trial_count=prior_trial_count,
                        on_trial=update_live_dashboard if continuous else None,
                        on_improvement=persist_train_improvement if continuous else None,
                    )
                except KeyboardInterrupt:
                    interrupted = True
                    economic_result = {
                        "status": "INTERRUPTED", "reason": "USER_INTERRUPTION",
                        "candidates_tested": 0, "freeze_created": False, "economically_proven": False,
                    }
                except Exception as exc:  # noqa: BLE001 - technical failure is reported, never promoted
                    economic_result = {
                        "status": "TECHNICAL_FAILURE", "reason": f"{type(exc).__name__}: {exc}",
                        "candidates_tested": 0, "freeze_created": False, "economically_proven": False,
                    }
            overall_status = str(economic_result.get("status") or "TECHNICAL_FAILURE")
            if continuous and not interrupted and economic_result.get("continuous") is not True:
                waiting_reason = str(economic_result.get("reason") or "SAFE_INPUTS_NOT_REPLAYABLE")
                print(
                    "[3/4] Recherche suspendue faute d'un échantillon causal suffisant : "
                    + _human_reason(waiting_reason)
                    + ". Le tableau reste ouvert; Ctrl+C clôt proprement ce run.",
                    flush=True,
                )
                continuous_progress.update({
                    "phase": "attente : davantage de données SAFE causalement rejouables",
                    "last_trial_text": "aucun essai lancé : données insuffisantes",
                })
                economic_result.update({
                    "status": "RUNNING",
                    "reason": waiting_reason,
                    "continuous": True,
                    "continuous_progress": dict(continuous_progress),
                    "heldout_status": "PROTECTED_NOT_USED_DURING_CONTINUOUS_TUNING",
                    "economically_proven": False,
                })
                live_summary.update({
                    "status": "RUNNING",
                    "economic_result": economic_result,
                    "historical_replay": historical_replay,
                    "improvement_history": load_improvement_history(ROOT),
                })
                _atomic_text(
                    report_dir / "resultat.json",
                    json.dumps(live_summary, ensure_ascii=False, indent=2) + "\n",
                )
                _write_economic_html_report(report_dir, live_summary)
                try:
                    while True:
                        time.sleep(1.0)
                except KeyboardInterrupt:
                    interrupted = True
                    economic_result["status"] = "INTERRUPTED"
                    economic_result["reason"] = "USER_CTRL_C_WHILE_WAITING_FOR_SAFE_EVIDENCE"
                    continuous_progress["phase"] = "arrêt propre; aucun essai n'avait assez de données"
                    economic_result["continuous_progress"] = dict(continuous_progress)
                    overall_status = "INTERRUPTED"
            if continuous:
                latest_stats = dict(last_trial)
                economic_result["train"] = {
                    "daily_mean_net_pnl_usd": economic_result.get("best_train_daily_usd"),
                    "statistics": {
                        "net_pnl_usd": economic_result.get("best_train_net_total_usd"),
                        "sample_count": economic_result.get("best_train_sample_count"),
                    },
                    "selection_score_metric": economic_result.get("best_train_score_metric"),
                    "selection_score": economic_result.get("best_train_score"),
                    "diagnostics": economic_result.get("best_train_diagnostics"),
                    "parameter_neighbor_diagnostics": economic_result.get("parameter_neighbor_diagnostics") or [],
                    "partial_fill_diagnostic": economic_result.get("partial_fill_diagnostic"),
                }
                economic_result["continuous_progress"] = dict(continuous_progress)
                economic_result["trial_accounting"] = trial_accounting
                economic_result["exploratory_freezes_created"] = exploratory_freeze_count
                economic_result["candidates_tested"] = int(
                    economic_result.get("candidates_tested_this_run") or 0
                )
                continuous_progress["phase"] = (
                    "arrêt propre et checkpoint sauvegardé"
                    if interrupted or overall_status == "INTERRUPTED"
                    else "fin de recherche"
                )
            frozen_train_records = []
            for improvement_index, improvement in enumerate(
                economic_result.get("train_improvements") or [], start=1
            ):
                exploratory = {
                    "freeze_created": True,
                    "economically_proven": False,
                    "status": "TRAIN_ONLY_EXPLORATORY_IMPROVEMENT",
                    "selected_candidate": improvement.get("candidate"),
                    "train": improvement.get("train"),
                }
                record = record_frozen_candidate(
                    ROOT,
                    f"{run_id}-train-{improvement_index:04d}",
                    exploratory,
                    current_copy_vault,
                )
                if record is not None:
                    frozen_train_records.append(record)
            if not continuous:
                economic_result["exploratory_freezes_created"] = len(frozen_train_records)
            economic_result["exploratory_freeze_records"] = frozen_train_records
            if economic_result.get("freeze_created") is True:
                candidate = economic_result.get("selected_candidate")
                candidate_path = report_dir / "CANDIDAT_GELE.json"
                candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                latest = ROOT / "runtime" / "codex_research" / "COPY_VAULT_LOCAL_LAB_CANDIDATE.json"
                latest.write_text(json.dumps({
                    "source_run": run_id, "status": overall_status,
                    "economically_proven": economic_result.get("economically_proven") is True,
                    "candidate": candidate,
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                economic_result["candidate_freeze_path"] = str(candidate_path)
                if not continuous:
                    frozen_record = record_frozen_candidate(
                        ROOT, run_id, economic_result, current_copy_vault
                    )
                    economic_result["immutable_history_record"] = frozen_record
            if overall_status in {"UNMEASURABLE", "MORE_DATA"} and dataset_root is None:
                print(
                    "[4/4] Données récentes non rejouables : bascule sur le corpus historique exécutable...",
                    flush=True,
                )
                historical_replay = run_historical_trade_replay(
                    ROOT,
                    progress=lambda message: print(f"[4/4] {message}", flush=True),
                )
                if historical_replay.get("improvement_found") is True:
                    best = dict(historical_replay.get("best_candidate") or {})
                    baseline = dict(historical_replay.get("baseline") or {})
                    exploratory = {
                        "freeze_created": True,
                        "economically_proven": False,
                        "status": "HISTORICAL_TRAIN_CANDIDATE_FROZEN",
                        "selected_candidate": {
                            "schema_version": "hypersmart.copy_vault_historical_candidate.v1",
                            "source": historical_replay.get("source"),
                            "configuration": {
                                key: best.get(key) for key in (
                                    "filter", "capital_usd", "fee_multiplier",
                                    "spread_multiplier", "latency_multiplier",
                                    "slippage_multiplier", "mechanism_archetypes",
                                )
                            },
                        },
                        "train": {"daily_mean_net_pnl_usd": best.get("daily_net_pnl_usd")},
                    }
                    historical_replay["immutable_history_record"] = record_frozen_candidate(
                        ROOT,
                        run_id + "-historical",
                        exploratory,
                        {"train": {"daily_mean_net_pnl_usd": baseline.get("daily_net_pnl_usd")}},
                    )

    if economic_result.get("economically_proven") is True:
        freeze_verdict = "Une amélioration a passé TRAIN, VALIDATION, OOS et FORWARD à au moins +5 USD nets/jour."
    elif economic_result.get("freeze_created") is True:
        freeze_verdict = "Un candidat TRAIN a été gelé pour comparaison, mais il n'est PAS économiquement prouvé."
    elif int(economic_result.get("exploratory_freezes_created") or 0) > 0:
        latest_train_improvement = (economic_result.get("train_improvements") or [])[-1]
        latest_statistics = dict((latest_train_improvement.get("train") or {}).get("statistics") or {})
        latest_total = latest_statistics.get("net_pnl_usd")
        latest_samples = int(latest_statistics.get("sample_count") or 0)
        latest_text = (
            "non mesurable"
            if latest_total is None
            else f"{float(latest_total):+.6f} USD au total sur {latest_samples} trade(s) TRAIN"
        )
        freeze_verdict = (
            f"{int(economic_result.get('exploratory_freezes_created') or 0)} meilleurs scores "
            f"successifs TRAIN ont été gelés; le meilleur reste {latest_text}. Aucune stratégie "
            "améliorée n'est prouvée faute d'un échantillon VALIDATION/OOS/FORWARD suffisant."
        )
    elif historical_replay.get("improvement_found") is True:
        freeze_verdict = (
            "Une amélioration exploratoire du replay historique TRAIN a été gelée de façon "
            "immuable. Elle doit encore passer VALIDATION, OOS et FORWARD."
        )
    elif historical_replay.get("status") == "COMPLETED_EXPLORATORY":
        freeze_verdict = (
            f"{int(historical_replay.get('trial_count') or 0)} scénarios historiques ont été "
            "rejoués sans trouver mieux que le Copy-Vault actuel; les données fraîches restent "
            "non mesurables faute d'alignement causal signal/L2."
        )
    else:
        freeze_verdict = (
            "Aucune amélioration valide n'a été gelée : "
            + _human_reason(economic_result.get("reason"))
            + "."
        )
    improvement_history = load_improvement_history(ROOT)
    summary = {
        "run_id": run_id,
        "head": head,
        "paper_read_only": True,
        "network_or_collection_started": False,
        "freeze_verdict": freeze_verdict,
        "safe_inputs": safe_inputs,
        "current_copy_vault": current_copy_vault,
        "historical_replay": historical_replay,
        "improvement_history": improvement_history,
        "test_groups": groups,
        "economic_result": economic_result,
        "status": overall_status,
    }
    (report_dir / "resultat.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_lines = [
        "# Rapport du laboratoire quant Copy-Vault",
        "",
        f"- Exécution UTC : {run_id}",
        f"- HEAD testé : `{head}`",
        "- Mode : PAPER / READ-ONLY; aucun ordre, aucune collecte réseau.",
        f"- Verdict freeze : {freeze_verdict}",
        f"- Statut du laboratoire : **{summary['status']}**",
        "",
        "## Résumé simple",
        "",
        f"- Shards vérifiés : **{safe_inputs.get('verified_assets', 0)}**.",
        f"- Fills / carnets uniques : **{safe_inputs.get('unique_fills', 0)} / {safe_inputs.get('unique_books', 0)}**.",
        f"- SHA catalogue SAFE : `{safe_inputs.get('catalog_sha256') or 'non renseigné'}`.",
        f"- Empreinte corpus consommé : `{safe_inputs.get('selection_digest') or 'non renseignée'}`; octets décompressés : **{safe_inputs.get('selected_raw_bytes') or 0}**.",
        f"- Configurations réellement rejouées : **{economic_result.get('candidates_tested', 0)}**.",
        f"- Objectif : **{OBJECTIVE_USD_PER_DAY} USD nets/jour** avec **{PAPER_CAPITAL_USD} USD paper**.",
        f"- Candidat gelé : **{'OUI' if economic_result.get('freeze_created') else 'NON'}**.",
        f"- Améliorations TRAIN conservées : **{economic_result.get('exploratory_freezes_created', 0)}**.",
        f"- Économiquement prouvé : **{'OUI' if economic_result.get('economically_proven') else 'NON'}**.",
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
            "Le meilleur TRAIN n'est jamais une preuve. Une stratégie n'est déclarée prouvée que si "
            "les gates séparés VALIDATION, OOS et FORWARD passent également après coûts et liquidité.",
            "",
        ]
    )
    (report_dir / "RAPPORT.md").write_text("\n".join(report_lines), encoding="utf-8")
    html_report = _write_economic_html_report(report_dir, summary)
    print(f"\nRAPPORT DÉTAILLÉ : {report_dir / 'RAPPORT.md'}", flush=True)
    print(f"RÉSULTAT JSON : {report_dir / 'resultat.json'}", flush=True)
    print(f"INTERFACE : {html_report}", flush=True)
    if preflight_only:
        final_verdict = "pré-vérification SAFE terminée; aucun backtest lancé."
    elif interrupted:
        final_verdict = "interrompu proprement; rapport complet écrit, aucun faux succès."
    else:
        final_verdict = freeze_verdict
    print("VERDICT FINAL : " + final_verdict, flush=True)
    _open_report(html_report)
    if interrupted:
        return 130
    return 1 if overall_status in {"FAIL", "TECHNICAL_FAILURE"} else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="inspecte les modules et le freeze, sans lancer les tests",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help="workspace FULL/COLD certifié, préparé à partir des shards SAFE",
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="lance une campagne économique réelle sur --dataset-root, sans collecte",
    )
    parser.add_argument(
        "--safe-research",
        action="store_true",
        help="convertit les shards SAFE AlinaSync certifiés en workspace et lance la campagne",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="enchaîne les replays Copy-Vault TRAIN jusqu'à Ctrl+C avec checkpoint et HTML live",
    )
    parser.add_argument(
        "--legacy-local-economic", action="store_true",
        help="laboratoire economique historique Codex/Claude, opt-in et fail-closed",
    )
    args = parser.parse_args(argv)
    if args.legacy_local_economic:
        if args.safe_research or args.research or args.preflight_only or args.dataset_root is not None:
            parser.error("--legacy-local-economic est incompatible avec les autres modes")
        return run_economic_lab()
    if args.safe_research:
        if args.research or args.preflight_only or args.dataset_root is not None:
            parser.error("--safe-research est incompatible avec les autres modes")
        from tools.copy_vault_safe_bridge import SafeBridgeError, build_safe_copy_workspace

        restore_code = _ensure_copy_vault_alinasync(ROOT)
        if restore_code != 0:
            print(
                f"SAFE_RESEARCH_NO_GO: restauration AlinaSync Copy-Vault incomplète (code {restore_code})",
                flush=True,
            )
            return 2
        try:
            safe_result = build_safe_copy_workspace(ROOT)
        except (SafeBridgeError, OSError, ValueError, TypeError) as exc:
            print(f"SAFE_RESEARCH_NO_GO: {exc}", flush=True)
            return 2
        print(
            "ALINA_SAFE_SHARDS_CONSUMED=" + str(safe_result["selected_shards"])
            + " | FILLS_TOTAL=" + str(
                safe_result["counts"].get("copy_vault_fills", 0)
                + safe_result["counts"].get("copy_vault_snapshot", 0)
            )
            + " | FILLS_FORWARD=" + str(
                safe_result["counts"].get("copy_vault_fills", 0)
            )
            + " | FILLS_HISTORICAL_TRAIN=" + str(
                safe_result["counts"].get("copy_vault_snapshot", 0)
            )
            + " | L2=" + str(safe_result["counts"].get("copy_vault_l2", 0))
            + " | CATALOG_SHA256=" + str(safe_result["catalog_sha256"])
            + " | RAW_BYTES=" + str(safe_result["selected_raw_bytes"]),
            flush=True,
        )
        return run_economic_lab(
            dataset_root=Path(safe_result["workspace"]),
            supplied_safe_inputs=safe_result,
            continuous=args.continuous,
        )
    if args.continuous:
        parser.error("--continuous nécessite --safe-research")
    if args.research:
        if args.preflight_only:
            parser.error("--research et --preflight-only sont incompatibles")
        if args.dataset_root is None:
            parser.error("--research exige --dataset-root")
        from hl_observer.datasets.source_discovery import (
            is_dataset_workspace, discover_family_sources,
        )
        dataset = args.dataset_root.resolve()
        if not is_dataset_workspace(dataset):
            print(
                "RESEARCH_NO_GO: provenance FULL/COLD absente. "
                "Les fichiers de runtime/recovery/full/usable/unpacked ne sont "
                "pas automatiquement un workspace économique compatible. "
                "Ne pas les remplacer par des données factices.",
                flush=True,
            )
            return 2
        sources = discover_family_sources(dataset)
        copy_sources = sources.get("copy_vault") or []
        if not copy_sources:
            print(
                "RESEARCH_NO_GO: aucune source Copy-Vault reconnue dans le "
                "workspace; données SAFE téléchargées != données consommées.",
                flush=True,
            )
            return 2
        cmd = [
            sys.executable, "-u",
            str(ROOT / "tools" / "run_dataset_economic_campaigns.py"),
            "--root", str(dataset),
            "--no-start-collection",
        ]
        print(
            "RESEARCH_INPUT_WORKSPACE=" + str(dataset)
            + " COPY_VAULT_FILES=" + str(len(copy_sources)),
            flush=True,
        )
        print("RESEARCH_COMMAND=" + subprocess.list2cmdline(cmd), flush=True)
        return subprocess.run(
            cmd, cwd=ROOT, check=False,
            env={
                **os.environ,
                "HL_ENABLE_MAINNET_EXECUTION": "0",
                "HL_ENABLE_TESTNET_EXECUTION": "0",
                "REAL_MAINNET_TRADING": "false",
                "TESTNET_ONLY": "true",
                "PYTHONPATH": os.pathsep.join(
                    [str(ROOT / "src"), str(ROOT), os.environ.get("PYTHONPATH", "")]
                ),
            },
        ).returncode
    if args.dataset_root is not None:
        parser.error("--dataset-root nécessite --research")
    return run_lab(preflight_only=args.preflight_only)


if __name__ == "__main__":
    raise SystemExit(main())
