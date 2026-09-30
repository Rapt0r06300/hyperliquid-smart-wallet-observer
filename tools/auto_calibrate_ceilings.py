#!/usr/bin/env python3
"""Fail-closed ratchet for audit ceilings.

Ceilings are allowed to move only downward when measured debt improves.
Any measured value above its ceiling is a regression: this command reports
it and refuses to edit or commit anything.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.audit.cablage import auditer_les_modules
from hl_observer.audit.dette_cablage import DETTE_CABLAGE


class Ceiling(NamedTuple):
    name: str
    current_value: int
    ceiling: int
    file_path: Path
    variable_name: str


def _read_python_var(file_path: Path, var_name: str) -> int | None:
    content = file_path.read_text(encoding="utf-8")
    match = re.search(rf"^{var_name}\s*=\s*(\d+)", content, re.MULTILINE)
    return int(match.group(1)) if match else None


def _write_python_var(file_path: Path, var_name: str, new_value: int) -> None:
    content = file_path.read_text(encoding="utf-8")
    pattern = rf"^{var_name}\s*=\s*\d+"
    if not re.search(pattern, content, re.MULTILINE):
        raise ValueError(f"Variable {var_name} not found in {file_path}")
    file_path.write_text(
        re.sub(pattern, f"{var_name} = {new_value}", content, flags=re.MULTILINE),
        encoding="utf-8",
    )


def measure_current_state() -> dict:
    ignore_prefixes = ("runtime/", "data/", "logs/", ".git/", "node_modules/")
    ignore_segments = ("__pycache__", "cli_pkg_DISABLED", "_archive")

    def collect(patterns: tuple[str, ...]) -> dict[str, str]:
        result: dict[str, str] = {}
        for pattern in patterns:
            for path in ROOT.glob(pattern):
                rel = path.relative_to(ROOT).as_posix()
                if any(rel.startswith(prefix) for prefix in ignore_prefixes):
                    continue
                if any(segment in ignore_segments for segment in rel.split("/")):
                    continue
                try:
                    result[rel] = path.read_text(encoding="utf-8-sig", errors="ignore")
                except OSError:
                    continue
        return result

    py = collect(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    tools = collect(("tools/**/*.py",))
    launchers = collect(
        (
            "*.cmd",
            "tools/**/*.cmd",
            "tools/**/*.ps1",
            "outils de test/**/*.cmd",
            "outils de test/**/*.ps1",
            "*.ps1",
            "*.sh",
            "config/**/*.yaml",
            "config/**/*.yml",
        )
    )
    verdict = auditer_les_modules(py, lanceurs=launchers, outils=tools)
    return {
        "orphelins": len(verdict.orphelins),
        "testes_non_branches": len(verdict.testes_non_branches),
        "outilles": len(verdict.outilles),
        "declared_debt": len(DETTE_CABLAGE),
        "fiable": verdict.fiable,
        "verdict": verdict,
    }


def _measured_ceilings(state: dict) -> list[Ceiling]:
    debt_file = ROOT / "src" / "hl_observer" / "audit" / "dette_cablage.py"
    guard_file = ROOT / "tests" / "test_risk_guards_no_limbo.py"
    values = (
        ("PLAFOND_DETTE", state["declared_debt"], debt_file),
        (
            "PLAFOND_MORTS_GLOBAL",
            state["testes_non_branches"] - state["declared_debt"],
            guard_file,
        ),
        ("PLAFOND_ORPHELINS_GLOBAL", state["orphelins"], guard_file),
    )
    result: list[Ceiling] = []
    for name, current, path in values:
        ceiling = _read_python_var(path, name)
        if ceiling is not None:
            result.append(Ceiling(name, current, ceiling, path, name))
    return result


def check_ceilings(state: dict) -> list[Ceiling]:
    """Return only safe ratchet candidates: measured value below ceiling."""
    return [item for item in _measured_ceilings(state) if item.current_value < item.ceiling]


def check_regressions(state: dict) -> list[Ceiling]:
    """Return regressions that must never be auto-accepted."""
    return [item for item in _measured_ceilings(state) if item.current_value > item.ceiling]


def auto_calibrate(state: dict, commit: bool = False) -> int:
    if not state["fiable"]:
        print("[REFUSE] Audit not reliable; ceilings remain unchanged.")
        return 2

    regressions = check_regressions(state)
    if regressions:
        print(f"[REFUSE] {len(regressions)} audit ceiling regression(s) detected:")
        for item in regressions:
            print(f"  {item.name}: measured={item.current_value} ceiling={item.ceiling}")
        print("Ceilings are immutable upward; fix or explicitly classify the debt instead.")
        return 1

    improvements = check_ceilings(state)
    if not improvements:
        print("[OK] No ceiling regression and no ratchet improvement.")
        return 0

    for item in improvements:
        print(f"[RATCHET] {item.name}: {item.ceiling} -> {item.current_value}")
    if not commit:
        print("Run with --commit to persist these downward-only changes.")
        return 1

    updated_files: set[Path] = set()
    for item in improvements:
        if item.current_value >= item.ceiling:
            raise RuntimeError("ratchet invariant violated: attempted non-decreasing update")
        _write_python_var(item.file_path, item.variable_name, item.current_value)
        updated_files.add(item.file_path)

    message = "chore(audit): ratchet ceilings downward\n\n" + "\n".join(
        f"- {item.name}: {item.ceiling} -> {item.current_value}" for item in improvements
    )
    try:
        for path in sorted(updated_files):
            subprocess.run(["git", "add", str(path)], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
        print(f"[ERROR] Git commit failed: {detail}")
        return 2
    print("[OK] Downward-only ratchet committed.")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fail-closed audit ceiling ratchet")
    parser.add_argument("--commit", action="store_true", help="persist safe downward-only ratchets")
    args = parser.parse_args()
    state = measure_current_state()
    print(
        "Audit state: "
        f"orphans={state['orphelins']} "
        f"tested_unwired={state['testes_non_branches']} "
        f"declared_debt={state['declared_debt']}"
    )
    return auto_calibrate(state, commit=args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
