"""AUDIT-C — Générateur du registre des flags HYPERSMART_ (auto depuis le code).

Scanne src/hl_observer, liste chaque flag, s'il est défini au launcher, et combien
de fichiers le consomment. Sortie: docs/CONFIG_FLAGS.md. Aucun réglage ne doit
exister sans être documenté, ni documenté sans exister. Pur (lecture seule).

Usage: python tools/gen_config_flags.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "hl_observer"
LAUNCHER = ROOT / "LANCER_HYPERSMART.cmd"
OUT = ROOT / "docs" / "CONFIG_FLAGS.md"
FLAG_RE = re.compile(r"HYPERSMART_[A-Z0-9_]+")


def scan() -> dict:
    code_flags: dict[str, int] = {}
    roots = [SRC, ROOT / "tools", ROOT / "hyper_smart_observer"]
    for root in roots:
        if not root.exists():
            continue
        for pat in ("*.py", "*.ps1", "*.cmd"):
            for p in root.rglob(pat):
                if "__pycache__" in str(p):
                    continue
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for flag in set(FLAG_RE.findall(txt)):
                    code_flags[flag] = code_flags.get(flag, 0) + 1
    launcher_flags = set()
    if LAUNCHER.exists():
        launcher_flags = set(FLAG_RE.findall(LAUNCHER.read_text(encoding="utf-8", errors="ignore")))
    return {"code": code_flags, "launcher": launcher_flags}


def build_markdown(data: dict) -> str:
    code, launcher = data["code"], data["launcher"]
    all_flags = sorted(set(code) | set(launcher))
    dead = [f for f in launcher if f not in code]
    lines = [
        "# Registre des flags de configuration (auto-généré)",
        "",
        f"Flags lus dans le code: {len(code)} · définis au launcher: {len(launcher)} · flags morts: {len(dead)}",
        "",
        "Un flag 'mort' est défini au launcher mais consommé nulle part dans le code.",
        "",
        "| Flag | Consommateurs (code) | Au launcher | Statut |",
        "|---|---:|:---:|---|",
    ]
    for f in all_flags:
        n = code.get(f, 0)
        at_launcher = "✓" if f in launcher else ""
        status = "MORT" if (f in launcher and n == 0) else ("code-only" if n and f not in launcher else "OK")
        lines.append(f"| `{f}` | {n} | {at_launcher} | {status} |")
    if dead:
        lines += ["", "## Flags morts à retirer", ""] + [f"- `{f}`" for f in sorted(dead)]
    return "\n".join(lines) + "\n"


def main() -> int:
    data = scan()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_markdown(data), encoding="utf-8")
    dead = [f for f in data["launcher"] if f not in data["code"]]
    print(f"écrit {OUT} · {len(data['code'])} flags code · {len(dead)} morts: {dead}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
