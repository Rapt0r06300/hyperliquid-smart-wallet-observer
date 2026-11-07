"""Q-006 — Table de parité .cmd ↔ code Python.

Vérifie que chaque flag HYPERSMART_ posé par le .cmd est lu par le code Python
(via runtime_flags.py ou os.getenv direct), et inversement. Les écarts signalent
soit une variable morte, soit un flag sans défaut sûr.

PAPER / READ-ONLY — aucun effet de bord.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


_SET_RE = re.compile(r'set\s+"(HYPERSMART_[A-Z0-9_]+)=', re.IGNORECASE)
_ENV_RE = re.compile(r"""(?:os\.(?:getenv|environ).*?[("']|HYPERSMART_)(HYPERSMART_[A-Z0-9_]+)""")
_ENV_RE2 = re.compile(r'["\']HYPERSMART_([A-Z0-9_]+)["\']')


def _extract_cmd_vars(cmd_path: str | Path) -> set[str]:
    text = Path(cmd_path).read_text(encoding="utf-8", errors="replace")
    return {m.group(1) for m in _SET_RE.finditer(text)}


def _extract_py_vars(src_dir: str | Path) -> set[str]:
    found: set[str] = set()
    for p in Path(src_dir).rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _ENV_RE2.finditer(text):
            found.add(f"HYPERSMART_{m.group(1)}")
    return found


_CMD_ONLY_KNOWN_SAFE = {
    "HYPERSMART_INTERACTIVE_LAUNCH",
    "HYPERSMART_PORT",
    "HYPERSMART_WARMUP_CORE_SEC",
    "HYPERSMART_NO_PAUSE",
    "HYPERSMART_PYTHON",
    "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW",
    "HYPERSMART_V13_TRAIN_INTERVAL_SEC",
}


def check_parity(
    cmd_path: str | Path,
    src_dir: str | Path,
) -> dict[str, Any]:
    cmd_vars = _extract_cmd_vars(cmd_path)
    py_vars = _extract_py_vars(src_dir)

    cmd_only = cmd_vars - py_vars - _CMD_ONLY_KNOWN_SAFE
    py_only = py_vars - cmd_vars

    return {
        "cmd_count": len(cmd_vars),
        "py_count": len(py_vars),
        "cmd_only": sorted(cmd_only),
        "py_only": sorted(py_only),
        "cmd_only_count": len(cmd_only),
        "py_only_count": len(py_only),
        "parity_ok": len(cmd_only) == 0 and len(py_only) == 0,
    }


def main() -> int:
    import json
    project_root = Path(__file__).resolve().parents[3]
    cmd_path = project_root / "LANCER_HYPERSMART.cmd"
    src_dir = project_root / "src" / "hl_observer"
    if not cmd_path.exists():
        print(f"[ERREUR] {cmd_path} introuvable")
        return 1
    result = check_parity(cmd_path, src_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["parity_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["check_parity"]
