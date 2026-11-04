"""Import the supplied Alina roadmap into a stable local, non-Agiflow index.

The source markdown remains the authority for task wording.  This importer only
normalizes numbering and metadata so implementation receipts can be attached
without editing the source export.  It never marks a task complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable


TASK_HEADER_RE = re.compile(
    r"^\s*- \[([ xX])\] \*\*Étape\s+(\d+)\s*/\s*(\d+)\*\*"
    r".*?\*\*\[([^]]+)\]\s+(.+)$"
)
SECTION_RE = re.compile(r"^###\s+(.+?)\s*$")
PRIORITY_RE = re.compile(r"\((P[0-4])(?:,|\))")
PRIORITY_FIELD_RE = re.compile(r"Priorité.*?(P[0-4])")
TRACKING_RE = re.compile(r"Suivi Codex.*?`([^`]+)`")
RECEIPT_RE = re.compile(r"Reçu de clôture.*?`([^`]+)`")
FILES_RE = re.compile(r"Fichiers vérifiés HEAD \(points d'entrée à examiner\).*?:\*?\s*(.+)$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _code_spans(value: str) -> list[str]:
    return re.findall(r"`([^`]+)`", value)


def _first_matching_line(block: str, patterns: Iterable[str]) -> str:
    for line in block.splitlines():
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in patterns):
            return line.strip()
    return ""


def parse_source(source: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    lines = source.read_text(encoding="utf-8").splitlines()
    source_hash = _sha256(source)
    headers: list[tuple[int, re.Match[str]]] = []
    section = ""
    sections: dict[int, str] = {}

    for index, line in enumerate(lines):
        section_match = SECTION_RE.match(line)
        if section_match:
            section = section_match.group(1)
        match = TASK_HEADER_RE.match(line)
        if match:
            headers.append((index, match))
            sections[index] = section

    tasks: list[dict[str, object]] = []
    for position, (start, match) in enumerate(headers, start=1):
        end = headers[position][0] if position < len(headers) else len(lines)
        block_lines = lines[start:end]
        block = "\n".join(block_lines)
        body = "\n".join(block_lines[1:])
        source_step = int(match.group(2))
        declared_total = int(match.group(3))
        source_id = match.group(4).strip()
        title = match.group(5).split("**", 1)[0].strip()
        priority_match = (
            PRIORITY_RE.search(match.group(5))
            or PRIORITY_RE.search(block)
            or PRIORITY_FIELD_RE.search(block)
        )
        priority = priority_match.group(1) if priority_match else "UNKNOWN"
        checked = match.group(1).lower() == "x"
        tracking_match = TRACKING_RE.search(block)
        receipt_match = RECEIPT_RE.search(block)
        files_line = _first_matching_line(body, (r"Fichiers vérifiés HEAD",))
        files_match = FILES_RE.search(files_line)
        tracked_files = _code_spans(files_match.group(1)) if files_match else []

        source_status = tracking_match.group(1).strip() if tracking_match else "UNSPECIFIED"
        source_receipt = receipt_match.group(1).strip() if receipt_match else "MISSING"
        source_verified = (
            checked
            and source_status == "VERIFIED_DONE"
            and source_receipt not in {"MISSING", "PENDING"}
        )
        tasks.append(
            {
                "ordinal": position,
                "step": source_step,
                "id": source_id,
                "title": title,
                "section": sections[start],
                "priority": priority,
                "source_line": start + 1,
                "source_checked": checked,
                "source_status": source_status,
                "source_receipt": source_receipt,
                "source_verified_done": source_verified,
                "tracked_files": tracked_files,
                "action_or_test": _first_matching_line(
                    body, (r"Action", r"Test", r"Correction", r"Oracle")
                ),
                "proof_requirement": _first_matching_line(
                    body, (r"Preuve", r"Livrable", r"Clôture")
                ),
                "local_status": "TODO",
                "local_evidence": [],
            }
        )

    if len(tasks) != 3120:
        raise ValueError(f"expected 3120 tasks, found {len(tasks)}")
    if [task["step"] for task in tasks] != list(range(1, 3121)):
        raise ValueError("source steps are not continuous from 1 to 3120")
    ids = [str(task["id"]) for task in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("source task IDs are not unique")

    metadata: dict[str, object] = {
        "roadmap_id": "ALINA-ROADMAP-3120",
        "title": "Alina Smart Flow — feuille de route locale numérotée",
        "task_count": len(tasks),
        "source_file": source.name,
        "source_sha256": source_hash,
        "source_bytes": source.stat().st_size,
        "source_lines": len(lines),
        "source_checked_tasks": sum(bool(task["source_checked"]) for task in tasks),
        "source_verified_done_tasks": sum(
            bool(task["source_verified_done"]) for task in tasks
        ),
        "status_policy": (
            "local_status remains TODO until a separate receipt proves the task "
            "on the exact code/data SHA; source text alone is never proof"
        ),
    }
    return metadata, tasks


def write_outputs(
    metadata: dict[str, object], tasks: list[dict[str, object]], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "ALINA_ROADMAP_3120.json"
    markdown_path = output_dir / "ALINA_ROADMAP_3120.md"
    manifest_path = output_dir / "ALINA_ROADMAP_3120.manifest.json"

    payload = {"metadata": metadata, "tasks": tasks}
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Alina Smart Flow — registre local de la feuille de route 3120",
        "",
        "> Registre de suivi local, sans Agiflow. Le texte source fourni par l'utilisateur "
        "reste la référence de contenu; ce fichier stabilise les IDs et les preuves.",
        f"> Source: `{metadata['source_file']}`",
        f"> SHA-256 source: `{metadata['source_sha256']}`",
        f"> Lignes source: {metadata['source_lines']} · Tâches: {metadata['task_count']}",
        "> Règle: aucune tâche n'est DONE sans reçu exact-SHA, commande, exit code et "
        "preuve vérifiable; les absences restent TODO/UNMEASURABLE.",
        "",
        "| N° | ID source | Priorité | Section | État local | Ligne source | Titre |",
        "|---:|---|---|---|---|---:|---|",
    ]
    for task in tasks:
        title = str(task["title"]).replace("|", "\\|")
        section = str(task["section"]).replace("|", "\\|")
        lines.append(
            f"| {int(task['ordinal']):04d} | `{task['id']}` | {task['priority']} | "
            f"{section} | `TODO` | {task['source_line']} | {title} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to ALINA_ROADMAP_3120.md")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/roadmap"),
        help="local output directory (default: docs/roadmap)",
    )
    args = parser.parse_args()
    metadata, tasks = parse_source(args.source)
    write_outputs(metadata, tasks, args.output_dir)
    print(
        f"imported={len(tasks)} source_sha256={metadata['source_sha256']} "
        f"output={args.output_dir} local_status=TODO"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
