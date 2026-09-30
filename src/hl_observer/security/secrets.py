from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*(?:[A-Z0-9_]*PRIVATE_KEY|SEED_PHRASE|MNEMONIC)\s*=\s*['\"]?([^'\"\s#]+)"
)
OPENAI_KEY_RE = re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")
SAFE_DISABLED_VALUES = {"false", "0", "none", "null", ""}


@dataclass(frozen=True, slots=True)
class SecretFinding:
    path: Path
    pattern: str


def contains_secret_pattern(text: str) -> bool:
    return bool(_secret_assignment_match(text) or OPENAI_KEY_RE.search(text))


def scan_file_for_secret(path: Path) -> SecretFinding | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if _secret_assignment_match(text):
        return SecretFinding(path=path, pattern="secret_assignment")
    if OPENAI_KEY_RE.search(text):
        return SecretFinding(path=path, pattern="openai_key")
    return None


def _secret_assignment_match(text: str) -> re.Match[str] | None:
    for match in SECRET_ASSIGNMENT_RE.finditer(text):
        value = (match.group(1) or "").strip().strip("'\"").rstrip(",;)").lower()
        if value in SAFE_DISABLED_VALUES:
            continue
        return match
    return None
