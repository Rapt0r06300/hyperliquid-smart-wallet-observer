from __future__ import annotations

import re
from pathlib import Path


_OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")


def scan_for_obvious_secrets(root: Path) -> tuple[bool, str]:
    suspicious: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "secret_scanner.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if "seed phrase" in text or _OPENAI_KEY_RE.search(text):
            suspicious.append(str(path))
    return not suspicious, f"suspicious secret markers: {len(suspicious)}"
