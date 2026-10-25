"""Readable, local-only Copy-Vault test launcher and freeze status report."""
from __future__ import annotations

import argparse
import ctypes
import html
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


def inspect_local_safe_corpus(root: Path) -> dict[str, Any]:
    """Read-only AlinaSync registry inspection; not economic source certification."""
    recovery = root / "runtime" / "recovery" / "full"
    result: dict[str, Any] = {"status": "NOT_CERTIFIED", "safe_registry_rows": None}
    try:
        restored = json.loads((recovery / "RESTORE_REPORT.json").read_text(encoding="utf-8"))
        expanded = json.loads((recovery / "UNPACK_REPORT.json").read_text(encoding="utf-8"))
        registry = recovery / "SAFE_SHARDS.sqlite3"
        catalog = (restored.get("catalog_verification") or {}).get("source_index_sha256")
        if not (
            restored.get("status") == "REPLAY_READY_COMPLETE"
            and (restored.get("classification") or {}).get("materialization_complete") is True
            and expanded.get("status") == "SAFE_UNPACK_COMPLETE"
            and catalog and expanded.get("catalog_index_sha256") == catalog
            and registry.is_file() and not registry.is_symlink()
        ):
            return result
        with sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0) as db:
            count = db.execute("SELECT COUNT(*) FROM current_safe_shards").fetchone()[0]
        expected = (restored.get("classification") or {}).get("usable_shards")
        unpack_count = expanded.get("certified_shards")
        status = (
            "RECEIPTS_MATCH_NOT_REHASHED"
            if type(count) is int and count > 0
            and type(expected) is int and expected == count
            and type(unpack_count) is int and unpack_count == count
            else "COUNT_MISMATCH"
        )
        return {"status": status, "safe_registry_rows": int(count)}
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
    target.write_text(
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
        "</main></body></html>",
        encoding="utf-8",
    )
    return target


def _open_report(path: Path) -> None:
    if os.environ.get("ALINA_QUANT_NO_OPEN") == "1" or os.name != "nt":
        return
    with suppress(OSError):
        os.startfile(path)  # type: ignore[attr-defined]


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

def _write_economic_html_report(report_dir: Path, summary: dict[str, Any]) -> Path:
    """Write a plain-French dashboard from the exact machine-readable result."""
    economic = dict(summary.get("economic_result") or {})
    current = dict(summary.get("current_copy_vault") or {})
    historical = dict(summary.get("historical_replay") or {})
    history = list(summary.get("improvement_history") or [])
    inputs = dict(summary.get("safe_inputs") or {})
    status = str(summary.get("status") or "UNKNOWN")
    status_class = "ok" if status == "PROVEN" else ("warn" if status in {"PROMISING", "MORE_DATA", "UNMEASURABLE", "PREFLIGHT_ONLY"} else "bad")
    def value(source: Mapping[str, Any], segment: str) -> float | None:
        row = source.get(segment) if isinstance(source.get(segment), dict) else {}
        value = row.get("daily_mean_net_pnl_usd")
        return None if value is None else float(value)
    def display(number: float | None) -> str:
        return "non mesurable" if number is None else f"{number:+.4f} USD/jour"
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
            f"<td>{display(row.get('candidate_daily_net_usd'))}</td>"
            f"<td>{display(row.get('improvement_usd_per_day'))}</td>"
            f"<td>{'OUI' if row.get('economically_proven') is True else 'NON'}</td>"
            "</tr>"
        )
    proven = economic.get("economically_proven") is True
    frozen = (
        economic.get("freeze_created") is True
        or historical.get("improvement_found") is True
    )
    target = report_dir / "RAPPORT.html"
    target.write_text(
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Laboratoire CopyVault</title><style>"
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
        f"<p><b>Objectif :</b> {OBJECTIVE_USD_PER_DAY:.2f} USD nets/jour avec {PAPER_CAPITAL_USD:.0f} USD paper.</p>"
        f"<p><b>Pourquoi :</b> {html.escape(_human_reason(economic.get('reason')))}</p></section>"
        "<h2>Comparaison avec le Copy‑Vault actuel</h2><section class='grid'>"
        f"<article class='card'><h3>Copy‑Vault actuel</h3><p class='answer'>{'≈ ' if current_daily is None and current_display_daily is not None else ''}{display(current_display_daily)}</p>"
        f"<p class='muted'>{html.escape(str(current.get('status') or 'NON MESURÉ'))} — {html.escape(_human_reason(current.get('reason')))}</p></article>"
        f"<article class='card'><h3>Meilleur candidat</h3><p class='answer'>{display(candidate_daily)}</p>"
        f"<p class='muted'>{html.escape(str((historical.get('status') if candidate_is_historical else economic.get('status')) or 'NON MESURÉ'))}</p></article>"
        f"<article class='card'><h3>Amélioration mesurée</h3><p class='answer'>{display(improvement)}</p>"
        "<p class='muted'>candidat moins Copy‑Vault actuel, uniquement si les deux sont comparables</p></article></section>"
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
        "<h2>Replay historique de secours</h2>"
        f"<p><b>{int(historical.get('trial_count') or 0)} scénarios</b> recalculés sur "
        f"<b>{int(historical.get('source_trade_count') or 0)} trades exécutables</b> conservés. "
        f"La recherche couvre {int(historical.get('unique_filter_count') or 0)} sous-ensembles distincts "
        f"issus de {int(historical.get('mechanism_count') or 0)} mécanismes. "
        f"Baseline comparable : {display(historical_baseline.get('daily_net_pnl_usd'))}; "
        f"meilleur candidat : {display(historical_best.get('daily_net_pnl_usd'))}; "
        f"écart : {display(historical.get('improvement_usd_per_day'))}. "
        "Résultat exploratoire TRAIN, conservé mais jamais présenté comme preuve OOS/forward.</p>"
        "<h2>Résultats économiques séparés</h2><section class='grid'>"
        f"<article class='card'><h3>TRAIN candidat</h3><p>{display(value(economic, 'train'))}</p></article>"
        f"<article class='card'><h3>VALIDATION</h3><p>actuel {display(value(current, 'validation'))}<br>candidat {display(value(economic, 'validation'))}</p></article>"
        f"<article class='card'><h3>OOS</h3><p>actuel {display(value(current, 'oos'))}<br>candidat {display(value(economic, 'oos'))}</p></article>"
        f"<article class='card'><h3>FORWARD</h3><p>actuel {display(value(current, 'forward'))}<br>candidat {display(value(economic, 'forward'))}</p></article></section>"
        "<h2>Historique conservé des améliorations</h2>"
        + (
            "<table><thead><tr><th>Run</th><th>État</th><th>Avant</th><th>Candidat</th><th>Gain</th><th>Prouvé</th></tr></thead>"
            f"<tbody>{''.join(history_rows)}</tbody></table>"
            if history_rows else "<p>Aucun candidat amélioré n'a encore pu être mesuré et gelé.</p>"
        )
        +
        "<h2>Ce que ce run a réellement fait</h2><ul>"
        f"<li>{int(inputs.get('verified_assets') or 0)} fichiers Copy‑Vault vérifiés à nouveau par taille et SHA‑256.</li>"
        f"<li>{int(inputs.get('unique_fills') or 0)} fills leader uniques et {int(inputs.get('unique_books') or 0)} carnets L2 uniques reconstruits.</li>"
        f"<li>{int(economic.get('candidates_tested') or 0) + int(historical.get('trial_count') or 0)} configurations réellement rejouées, coûts et liquidité observée inclus.</li>"
        "<li>Recherche sur TRAIN uniquement; VALIDATION, OOS et FORWARD ne servent jamais au réglage.</li>"
        "<li>Aucune collecte réseau, aucun ordre, aucune clé et aucune transaction.</li></ul>"
        f"<h2>Verdict simple</h2><p>{html.escape(str(summary.get('freeze_verdict') or ''))}</p>"
        f"<p class='path'>Données machine : {html.escape(str(report_dir / 'resultat.json'))}</p>"
        "</main></body></html>",
        encoding="utf-8",
    )
    return target

def run_economic_lab(*, preflight_only: bool = False, tests_only: bool = False) -> int:
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
        workspace = report_dir / "workspace"
        print("\n[1/4] Vérification SAFE : taille + SHA-256 de chaque shard Copy-Vault...", flush=True)
        safe_inputs = materialize_safe_workspace(recovery, workspace)
        print(
            f"      {safe_inputs.get('verified_assets', 0)} fichiers vérifiés; "
            f"{safe_inputs.get('unique_fills', 0)} fills; {safe_inputs.get('unique_books', 0)} carnets L2.",
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
            try:
                economic_result = run_local_campaign(
                    workspace,
                    progress=lambda message: print(f"[3/4] {message}", flush=True),
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
                frozen_record = record_frozen_candidate(
                    ROOT, run_id, economic_result, current_copy_vault
                )
                economic_result["immutable_history_record"] = frozen_record
            if overall_status in {"UNMEASURABLE", "MORE_DATA"}:
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
        f"- Configurations réellement rejouées : **{economic_result.get('candidates_tested', 0)}**.",
        f"- Objectif : **{OBJECTIVE_USD_PER_DAY} USD nets/jour** avec **{PAPER_CAPITAL_USD} USD paper**.",
        f"- Candidat gelé : **{'OUI' if economic_result.get('freeze_created') else 'NON'}**.",
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

        try:
            safe_result = build_safe_copy_workspace(ROOT)
        except (SafeBridgeError, OSError, ValueError, TypeError) as exc:
            print(f"SAFE_RESEARCH_NO_GO: {exc}", flush=True)
            return 2
        print(
            "ALINA_SAFE_SHARDS_CONSUMED=" + str(safe_result["selected_shards"])
            + " | FILLS=" + str(safe_result["counts"]["copy_vault_fills"])
            + " | L2=" + str(safe_result["counts"]["copy_vault_l2"]),
            flush=True,
        )
        args.research = True
        args.dataset_root = Path(safe_result["workspace"])
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
