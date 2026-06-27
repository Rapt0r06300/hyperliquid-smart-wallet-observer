from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


FIELDS = (
    "Titre",
    "URL",
    "Type",
    "Resume",
    "Pourquoi c'est utile",
    "Ce que ca prouve",
    "Ce que ca ne prouve pas",
    "Module concerne",
    "Decision a ameliorer",
    "UI concernee",
    "Temps reel concerne",
    "Risque securite",
    "Statut propose",
)


@dataclass(frozen=True, slots=True)
class ManualResearchItem:
    title: str
    url: str
    source_type: str
    summary: str
    usefulness: str
    proves: str
    does_not_prove: str
    module: str
    decision: str
    ui: str
    realtime: str
    security_risk: str
    proposed_status: str


@dataclass(frozen=True, slots=True)
class ManualResearchImport:
    input_path: Path
    output_path: Path
    items: tuple[ManualResearchItem, ...]
    write_warning: str = ""


def write_manual_research_template(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MEGA V1 Manual Research Inbox",
        "",
        "Colle une ou plusieurs sources avec ce format. Une source utilisateur n'est jamais une verite automatique.",
        "",
        "## Source 1",
    ]
    lines.extend(f"{field}: " for field in FIELDS)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def import_manual_research(path: Path, *, output_path: Path = Path("data/reports/manual_research_items.json")) -> ManualResearchImport:
    if not path.exists():
        write_manual_research_template(path)
    items = tuple(_parse_items(path.read_text(encoding="utf-8-sig")))
    warning = _safe_write_text(
        output_path,
        json.dumps([asdict(item) for item in items], indent=2, sort_keys=True, ensure_ascii=False),
    )
    return ManualResearchImport(input_path=path, output_path=output_path, items=items, write_warning=warning or "")


def format_manual_research_import(result: ManualResearchImport) -> str:
    lines = [
        "manual_research_import=local_only",
        f"input={result.input_path}",
        f"output={result.output_path}",
        f"items={len(result.items)}",
    ]
    if result.write_warning:
        lines.append(f"write_warning={result.write_warning}")
    for item in result.items[:20]:
        lines.append(f"- {item.title or 'Sans titre'} | {item.source_type or 'UNKNOWN'} | {item.url or 'no-url'}")
    return "\n".join(lines)


def _safe_write_text(path: Path, text: str) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"{path}: {exc.__class__.__name__}: {exc}"
    return None


def _parse_items(text: str) -> list[ManualResearchItem]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## ") and current:
            blocks.append(current)
            current = {}
            current_key = None
            continue
        matched = False
        for field in FIELDS:
            prefix = f"{field}:"
            if line.startswith(prefix):
                current[field] = line.removeprefix(prefix).strip()
                current_key = field
                matched = True
                break
        if not matched and current_key and line:
            current[current_key] = (current.get(current_key, "") + " " + line).strip()
    if current:
        blocks.append(current)
    return [
        ManualResearchItem(
            title=block.get("Titre", ""),
            url=block.get("URL", ""),
            source_type=block.get("Type", ""),
            summary=block.get("Resume", ""),
            usefulness=block.get("Pourquoi c'est utile", ""),
            proves=block.get("Ce que ca prouve", ""),
            does_not_prove=block.get("Ce que ca ne prouve pas", ""),
            module=block.get("Module concerne", ""),
            decision=block.get("Decision a ameliorer", ""),
            ui=block.get("UI concernee", ""),
            realtime=block.get("Temps reel concerne", ""),
            security_risk=block.get("Risque securite", ""),
            proposed_status=block.get("Statut propose", ""),
        )
        for block in blocks
        if any(value.strip() for value in block.values())
    ]
