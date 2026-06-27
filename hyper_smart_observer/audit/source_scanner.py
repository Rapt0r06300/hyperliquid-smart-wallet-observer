from __future__ import annotations

from pathlib import Path


def scan_source_forbidden_terms(root: Path) -> dict[str, list[str]]:
    terms = {
        "exchange_path": "/" + "exchange",
        "sign_call": "." + "sign" + "(",
        "place_order": "place_order(",
        "private_key_literal": "private key",
    }
    findings: dict[str, list[str]] = {key: [] for key in terms}
    for path in root.rglob("*.py"):
        if path.name == "source_scanner.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for key, term in terms.items():
            if term in text:
                findings[key].append(str(path))
    return findings
