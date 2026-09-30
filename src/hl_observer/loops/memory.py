from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.loops.decision_trace import traces_to_dicts
from hl_observer.loops.models import ExecutionFeedback, LearningSummary, LoopRunResult, ResearchThesis
from hl_observer.runtime.session_logs import default_logs_to_send_dir


def default_loop_memory_dir(project_root: Path | None = None) -> Path:
    root = project_root or Path.cwd()
    return root / "runtime" / "learning"


@dataclass(slots=True)
class LoopMemoryStore:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def events_path(self) -> Path:
        return self.root / "loop_events.jsonl"

    @property
    def latest_json_path(self) -> Path:
        return self.root / "latest_loop_result.json"

    @property
    def latest_markdown_path(self) -> Path:
        return self.root / "latest_loop_report.md"

    @property
    def latest_trace_path(self) -> Path:
        return self.root / "latest_decision_trace.json"

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        entry = {"event_type": event_type, "payload": payload}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str) + "\n")

    def write_result(self, result: LoopRunResult) -> None:
        result_json = json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True, default=str)
        trace_json = json.dumps(traces_to_dicts(result), ensure_ascii=False, indent=2, sort_keys=True, default=str)
        report_text = self.render_markdown(result)
        self.latest_json_path.write_text(result_json, encoding="utf-8")
        self.latest_trace_path.write_text(
            trace_json,
            encoding="utf-8",
        )
        self.latest_markdown_path.write_text(report_text, encoding="utf-8")
        self._mirror_latest_to_logs_to_send(
            result_json=result_json,
            trace_json=trace_json,
            report_text=report_text,
        )

    def record_thesis(self, thesis: ResearchThesis) -> None:
        self.append_event("research_thesis", thesis.to_dict())

    def record_feedback(self, feedback: ExecutionFeedback) -> None:
        self.append_event("execution_feedback", feedback.to_dict())

    def record_learning(self, summary: LearningSummary) -> None:
        self.append_event("learning_summary", summary.to_dict())

    def latest_report_text(self) -> str:
        if self.latest_markdown_path.exists():
            return self.latest_markdown_path.read_text(encoding="utf-8")
        return "# HyperSmart Loop Report\n\nAucune boucle locale n'a encore ete executee.\n"

    def _mirror_latest_to_logs_to_send(self, *, result_json: str, trace_json: str, report_text: str) -> None:
        """Mirror the loop evidence into logs/logs a envoyer for user-side QA bundles."""

        project_root = self._project_root()
        log_dir = default_logs_to_send_dir(project_root)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "latest_loop_result.json").write_text(result_json, encoding="utf-8")
            (log_dir / "latest_decision_trace.json").write_text(trace_json, encoding="utf-8")
            (log_dir / "latest_loop_report.md").write_text(report_text, encoding="utf-8")
        except OSError:
            # Evidence mirroring is best-effort; the canonical runtime/learning files above remain authoritative.
            return

    def _project_root(self) -> Path:
        if self.root.name == "learning" and self.root.parent.name == "runtime":
            return self.root.parent.parent
        if self.root.name == "learning":
            return self.root.parent
        return Path.cwd()

    @staticmethod
    def render_markdown(result: LoopRunResult) -> str:
        lines = [
            "# HyperSmart Loop Report",
            "",
            "Research only. Mainnet read-only. Testnet locked unless explicitly confirmed.",
            "",
            f"- Run: `{result.run_id}`",
            f"- Thesis: `{result.thesis.thesis_id}` / `{result.thesis.status}`",
            f"- Source: `{result.thesis.source}`",
            f"- Coins vus: `{result.thesis.coins_seen}`",
            f"- L2 books vus: `{result.thesis.l2_books_seen}`",
            f"- Wallets vus: `{result.thesis.wallets_seen}`",
            f"- Fills vus: `{result.thesis.fills_seen}`",
            f"- Decisions: `{result.learning.total_decisions}`",
            f"- Testnet accepted: `{result.learning.accepted_testnet}`",
            f"- Rejected: `{result.learning.rejected}`",
            f"- No-trade: `{result.learning.no_trade}`",
            "",
            "## Notes",
        ]
        lines.extend(f"- {note}" for note in (result.thesis.notes or ["Aucune note."]))
        lines.append("")
        lines.append("## Raisons recurrentes")
        if result.learning.recurring_reasons:
            lines.extend(f"- `{reason}`: {count}" for reason, count in result.learning.recurring_reasons.items())
        else:
            lines.append("- Aucune raison recurrente.")
        lines.append("")
        lines.append("## Prochaines actions")
        lines.extend(f"- {action}" for action in result.learning.next_actions)
        return "\n".join(lines) + "\n"
