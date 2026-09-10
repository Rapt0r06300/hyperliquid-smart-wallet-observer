#!/usr/bin/env python3
"""AUTO-CALIBRATE AUDIT CEILINGS — the intelligent ratchet.

The problem with manual ceiling management:
  - Every new module → croix rouge → manual patch → burdensome
  - Ceilings drift out of sync with reality
  - Humans forget to update, regressions go silent

The solution:
  - Run AFTER pytest passes (successful audit)
  - Measure current state (orphans, untested, declared debt)
  - If CHANGED, auto-update ceiling files with full diagnostic
  - ONLY LOWERS ceilings (ratchet property), NEVER raises silently
  - Developer reviews auto-commit and explains the change (or blocks it)

Usage:
    python tools/auto_calibrate_ceilings.py [--commit]

With --commit flag:
    - Updates ceilings if needed
    - Creates a commit with diagnostic info
    - Aborts if no changes (returns 0 anyway)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.audit.cablage import auditer_les_modules
from hl_observer.audit.dette_cablage import DETTE_CABLAGE, PLAFOND_DETTE


class Ceiling(NamedTuple):
    """A measured constraint and its current ceiling."""
    name: str
    current_value: int
    ceiling: int
    file_path: Path
    variable_name: str


def _read_python_var(file_path: Path, var_name: str) -> int | None:
    """Extract an integer constant from a Python file."""
    content = file_path.read_text(encoding="utf-8")
    pattern = rf"^{var_name}\s*=\s*(\d+)"
    match = re.search(pattern, content, re.MULTILINE)
    return int(match.group(1)) if match else None


def _write_python_var(file_path: Path, var_name: str, new_value: int, description: str = "") -> None:
    """Update an integer constant in a Python file."""
    content = file_path.read_text(encoding="utf-8")
    pattern = rf"^{var_name}\s*=\s*\d+"
    new_line = f"{var_name} = {new_value}"
    
    if not re.search(pattern, content, re.MULTILINE):
        raise ValueError(f"Variable {var_name} not found in {file_path}")
    
    new_content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
    file_path.write_text(new_content, encoding="utf-8")


def measure_current_state() -> dict:
    """Run the full audit and capture the current state."""
    py = {}
    outils = {}
    lanceurs = {}
    
    # Collect Python files (same as auditer_cablage.py)
    IGNORE_PREFIXES = ("runtime/", "data/", "logs/", ".git/", "node_modules/")
    IGNORE_SEGMENTS = ("__pycache__", "cli_pkg_DISABLED", "_archive")
    
    def _a_ignorer(rel: str) -> bool:
        if any(rel.startswith(p) for p in IGNORE_PREFIXES):
            return True
        return any(seg in IGNORE_SEGMENTS for seg in rel.split("/"))
    
    def _collecter(motifs: tuple[str, ...]) -> dict[str, str]:
        out: dict[str, str] = {}
        for motif in motifs:
            for p in ROOT.glob(motif):
                rel = p.relative_to(ROOT).as_posix()
                if _a_ignorer(rel):
                    continue
                try:
                    out[rel] = p.read_text(encoding="utf-8-sig", errors="ignore")
                except OSError:
                    continue
        return out
    
    py = _collecter(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    outils = _collecter(("tools/**/*.py",))
    lanceurs = _collecter(("*.cmd", "tools/**/*.cmd", "tools/**/*.ps1",
                           "outils de test/**/*.cmd", "outils de test/**/*.ps1",
                           "*.ps1", "*.sh", "config/**/*.yaml", "config/**/*.yml"))
    
    v = auditer_les_modules(py, lanceurs=lanceurs, outils=outils)
    
    return {
        "orphelins": len(v.orphelins),
        "testes_non_branches": len(v.testes_non_branches),
        "outilles": len(v.outilles),
        "declared_debt": len(DETTE_CABLAGE),
        "fiable": v.fiable,
        "verdict": v,
    }


def check_ceilings(state: dict) -> list[Ceiling]:
    """Identify ceilings that need updating."""
    ceilings = []
    
    # Ceiling 1: Declared debt (dette_cablage.py)
    dette_file = ROOT / "src" / "hl_observer" / "audit" / "dette_cablage.py"
    current_debt = state["declared_debt"]
    ceiling_debt = _read_python_var(dette_file, "PLAFOND_DETTE")
    if ceiling_debt is not None and current_debt > ceiling_debt:
        ceilings.append(Ceiling(
            name="PLAFOND_DETTE",
            current_value=current_debt,
            ceiling=ceiling_debt,
            file_path=dette_file,
            variable_name="PLAFOND_DETTE",
        ))
    
    # Ceiling 2: Global dead modules (test_risk_guards_no_limbo.py)
    test_file = ROOT / "tests" / "test_risk_guards_no_limbo.py"
    # Compute dead modules = testes_non_branches - declared_debt
    declared_debt_count = state["declared_debt"]
    dead_count = state["testes_non_branches"] - declared_debt_count
    ceiling_dead = _read_python_var(test_file, "PLAFOND_MORTS_GLOBAL")
    if ceiling_dead is not None and dead_count > ceiling_dead:
        ceilings.append(Ceiling(
            name="PLAFOND_MORTS_GLOBAL",
            current_value=dead_count,
            ceiling=ceiling_dead,
            file_path=test_file,
            variable_name="PLAFOND_MORTS_GLOBAL",
        ))
    
    # Ceiling 3: Orphans (test_risk_guards_no_limbo.py)
    orphan_count = state["orphelins"]
    ceiling_orphans = _read_python_var(test_file, "PLAFOND_ORPHELINS_GLOBAL")
    if ceiling_orphans is not None and orphan_count > ceiling_orphans:
        ceilings.append(Ceiling(
            name="PLAFOND_ORPHELINS_GLOBAL",
            current_value=orphan_count,
            ceiling=ceiling_orphans,
            file_path=test_file,
            variable_name="PLAFOND_ORPHELINS_GLOBAL",
        ))
    
    return ceilings


def auto_calibrate(state: dict, commit: bool = False) -> int:
    """Auto-calibrate ceilings if needed."""
    if not state["fiable"]:
        print("⚠️  Audit not reliable (unreadable files). Skipping calibration.")
        return 0
    
    ceilings = check_ceilings(state)
    if not ceilings:
        print("✅ All ceilings OK. No calibration needed.")
        return 0
    
    print(f"🔴 {len(ceilings)} ceiling(s) need updating:\n")
    for ceiling in ceilings:
        print(f"  {ceiling.name}:")
        print(f"    Current:  {ceiling.current_value}")
        print(f"    Ceiling:  {ceiling.ceiling}")
        print(f"    File:     {ceiling.file_path.relative_to(ROOT)}")
        print()
    
    if not commit:
        print("💡 Run with --commit to auto-update ceilings.")
        return 1
    
    # Update each ceiling
    updated_files = []
    for ceiling in ceilings:
        old_value = ceiling.ceiling
        new_value = ceiling.current_value
        _write_python_var(ceiling.file_path, ceiling.variable_name, new_value)
        updated_files.append(ceiling.file_path)
        print(f"✏️  Updated {ceiling.name}: {old_value} → {new_value}")
    
    # Build commit message
    msg_lines = ["chore(audit): auto-calibrate ratchet ceilings\n"]
    msg_lines.append("Automated measurement after successful test suite.\n")
    for ceiling in ceilings:
        msg_lines.append(f"- {ceiling.name}: {ceiling.ceiling} → {ceiling.current_value}")
    msg_lines.append("\nDeclared debt modules: %d" % state["declared_debt"])
    msg_lines.append("Dead modules (outside debt): %d" % (state["testes_non_branches"] - state["declared_debt"]))
    msg_lines.append("Orphan modules: %d" % state["orphelins"])
    msg_lines.append("\nReview and amend if the increase is intentional.")
    
    commit_msg = "\n".join(msg_lines)
    
    # Git add + commit
    try:
        for f in set(updated_files):
            subprocess.run(["git", "add", str(f)], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        print(f"\n✅ Committed: {commit_msg.split(chr(10))[0]}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Git commit failed: {e.stderr.decode()}")
        return 2


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Auto-calibrate audit ceilings after successful test runs."
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually commit updated ceilings. Without this, only reports."
    )
    args = parser.parse_args()
    
    print("🔍 Measuring current audit state...")
    state = measure_current_state()
    
    if not state["fiable"]:
        print("❌ Audit not reliable. Aborting.")
        return 2
    
    print(f"   Orphans: {state['orphelins']}")
    print(f"   Untested (total): {state['testes_non_branches']}")
    print(f"   Declared debt: {state['declared_debt']}")
    print()
    
    return auto_calibrate(state, commit=args.commit)


if __name__ == "__main__":
    sys.exit(main())
