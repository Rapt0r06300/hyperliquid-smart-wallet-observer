"""Régénère les hashes SHA-256 des receipts roadmap après modification de fichiers source.

Usage :
    python tools/regenerer_receipts.py

Lit le fichier receipts, recalcule les hashes pour chaque receipt dont au moins un
fichier a changé, et réécrit le fichier avec les hashes mis à jour.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from alina_roadmap_progress import _file_set_fingerprint  # noqa: E402

RECEIPTS_PATH = ROOT / "runtime" / "roadmap" / "ALINA_ROADMAP_3120.receipts.jsonl"


def main() -> int:
    if not RECEIPTS_PATH.exists():
        print("Fichier de receipts introuvable :", RECEIPTS_PATH)
        return 1

    lines = RECEIPTS_PATH.read_text(encoding="utf-8").splitlines()
    updated_count = 0
    skipped_missing = 0
    new_lines: list[str] = []

    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue
        row = json.loads(line)
        files = row.get("files")
        file_sha256 = row.get("file_sha256")

        if not isinstance(files, list) or not isinstance(file_sha256, dict):
            new_lines.append(line)
            continue

        needs_update = False
        current_hashes: dict[str, str] = {}
        all_exist = True
        for name in files:
            p = ROOT / str(name)
            if not p.exists():
                all_exist = False
                break
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            current_hashes[str(name)] = h
            if str(file_sha256.get(str(name), "")).lower() != h.lower():
                needs_update = True

        if not all_exist:
            skipped_missing += 1
            new_lines.append(line)
            continue

        if needs_update and len(current_hashes) == len(files):
            row["file_sha256"] = current_hashes
            row["sha"] = _file_set_fingerprint(
                [str(n) for n in files], current_hashes
            )
            new_lines.append(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            )
            updated_count += 1
        else:
            new_lines.append(line)

    RECEIPTS_PATH.write_text(
        "\n".join(new_lines) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[regenerer_receipts] {updated_count} receipts mis à jour")
    if skipped_missing:
        print(f"[regenerer_receipts] {skipped_missing} receipts ignorés (fichiers manquants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
