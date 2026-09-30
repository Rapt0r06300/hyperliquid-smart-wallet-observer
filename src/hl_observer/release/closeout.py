from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hl_observer.release.quality_gates import QualityGateReport, format_quality_gates, run_quality_gates


@dataclass(frozen=True, slots=True)
class CloseoutReport:
    report_path: Path
    quality: QualityGateReport


def write_closeout_report(root: Path = Path("."), *, log_dir: Path | None = None) -> CloseoutReport:
    root = root.resolve()
    quality = run_quality_gates(root, log_dir=log_dir)
    output = root / "docs" / "release" / "MEGA_V1_CLOSEOUT_REPORT.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MEGA V1 Closeout Report",
        "",
        "Mode: simulation locale / read-only.",
        "",
        "## Quality Gates",
        "",
        "```text",
        format_quality_gates(quality),
        "```",
        "",
        "## Securite",
        "",
        "- Aucun argent reel.",
        "- Aucun mainnet.",
        "- Aucune signature.",
        "- Aucune cle privee.",
        "- Aucun ordre.",
        "- Aucun testnet actif.",
        "- Dashboard read-only.",
        "",
        "## Prochaine action",
        "",
        "Si `GATE_REALTIME` est BLOCKED, relancer le lanceur ou `realtime-replay` pour produire un flux local frais; ensuite analyser `simulation-loss-report`.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return CloseoutReport(report_path=output, quality=quality)

