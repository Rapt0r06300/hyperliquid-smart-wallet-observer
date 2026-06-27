from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from hl_observer.research.manual_research_importer import ManualResearchItem, import_manual_research


@dataclass(frozen=True, slots=True)
class ClassifiedResearchItem:
    title: str
    url: str
    reliability: str
    module: str
    decision: str
    status: str
    reason: str


def classify_manual_research(
    inbox_path: Path,
    *,
    output_path: Path = Path("docs/release/MEGA_V1_MANUAL_RESEARCH_CLASSIFICATION.json"),
) -> tuple[ClassifiedResearchItem, ...]:
    imported = import_manual_research(inbox_path, output_path=_import_output_for(output_path))
    rows = tuple(_classify(item) for item in imported.items)
    _safe_write_text(
        output_path,
        json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True, ensure_ascii=False),
    )
    return rows


def write_research_to_feature_map(
    inbox_path: Path,
    *,
    output_path: Path = Path("docs/release/MEGA_V1_MANUAL_RESEARCH_TO_FEATURE_MAP.md"),
) -> Path:
    rows = classify_manual_research(inbox_path, output_path=output_path.with_suffix(".classification.json"))
    lines = [
        "# MEGA V1 Manual Research To Feature Map",
        "",
        "| Source | Reliability | Module | Decision | Status | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.title or row.url or 'Sans titre'} | {row.reliability} | {row.module or '-'} | "
            f"{row.decision or '-'} | {row.status} | {row.reason} |"
        )
    if not rows:
        lines.append("| aucune source | NOT_USABLE | - | - | BLOCKED_WITH_PROOF | Inbox vide |")
    _safe_write_text(output_path, "\n".join(lines) + "\n")
    return output_path


def format_classified_research(rows: tuple[ClassifiedResearchItem, ...]) -> str:
    lines = ["manual_research_classification=local_only", f"items={len(rows)}"]
    for row in rows[:20]:
        lines.append(f"- {row.reliability} | {row.status} | {row.title or row.url or 'Sans titre'} | {row.reason}")
    return "\n".join(lines)


def _classify(item: ManualResearchItem) -> ClassifiedResearchItem:
    url = item.url.lower()
    text = " ".join(
        [
            item.source_type,
            item.summary,
            item.usefulness,
            item.proves,
            item.does_not_prove,
            item.security_risk,
        ]
    ).lower()
    reliability = "UNVERIFIED"
    reason = "Source manuelle a verifier avant implementation."
    if "hyperliquid.gitbook.io" in url:
        reliability = "OFFICIAL_HYPERLIQUID"
        reason = "Documentation officielle Hyperliquid."
    elif "github.com" in url:
        reliability = "OPEN_SOURCE_CODE"
        reason = "Code open-source a auditer avant reprise."
    elif "reddit.com" in url or "x.com" in url or "twitter.com" in url:
        reliability = "OSINT_CLAIM"
        reason = "Claim public non suffisant pour modifier le risque."
    elif "dwellir" in url or "baselight" in url or "hydromancer" in url:
        reliability = "DATA_PROVIDER"
        reason = "Source utile pour dataset local ou historique."
    if "private key" in text or "signature" in text or "execute" in text or "ordre reel" in text:
        status = "REFUSED_DANGEROUS"
        reason = "La source mentionne une execution ou un secret; refus pour ce sprint."
    elif reliability in {"OFFICIAL_HYPERLIQUID", "DATA_PROVIDER", "OPEN_SOURCE_CODE"}:
        status = "ACTIONABLE_AFTER_TEST"
    elif reliability == "OSINT_CLAIM":
        status = "RESEARCH_ONLY"
    else:
        status = "UNVERIFIED"
    return ClassifiedResearchItem(
        title=item.title,
        url=item.url,
        reliability=reliability,
        module=item.module,
        decision=item.decision,
        status=status,
        reason=reason,
    )


def format_feature_map(path: Path) -> str:
    return f"research_to_feature_map={path}"


def _import_output_for(output_path: Path) -> Path:
    if output_path.name:
        return output_path.with_name("manual_research_items.json")
    return Path("data/reports/manual_research_items.json")


def _safe_write_text(path: Path, text: str) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"{path}: {exc.__class__.__name__}: {exc}"
    return None
