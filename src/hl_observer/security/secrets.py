from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*(?:[A-Z0-9_]*PRIVATE_KEY|SEED_PHRASE|MNEMONIC)\s*=\s*['\"]?[^'\"\s#]+"
)
OPENAI_KEY_RE = re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")


@dataclass(frozen=True, slots=True)
class SecretFinding:
    path: Path
    pattern: str


def contains_secret_pattern(text: str) -> bool:
    return bool(SECRET_ASSIGNMENT_RE.search(text) or OPENAI_KEY_RE.search(text))


def scan_file_for_secret(path: Path) -> SecretFinding | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if SECRET_ASSIGNMENT_RE.search(text):
        return SecretFinding(path=path, pattern="secret_assignment")
    if OPENAI_KEY_RE.search(text):
        return SecretFinding(path=path, pattern="openai_key")
    return None
