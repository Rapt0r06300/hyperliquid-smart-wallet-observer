from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import shortlist_path
from hyper_smart_observer.copy_mode.copy_models import LeaderStatus, to_jsonable, utc_now
from hyper_smart_observer.copy_mode.leaderboard_selector import is_full_wallet_address, load_shortlist_entries
from hyper_smart_observer.runtime.runtime_check import scan_runtime_files


@dataclass(frozen=True)
class CopyPreflightIssue:
    level: str
    code: str
    message: str


@dataclass(frozen=True)
class CopyPreflightReport:
    generated_at: object
    shortlist_path: str
    shortlist_exists: bool
    total_entries: int
    shortlisted_entries: int
    rejected_entries: int
    leaders_planned: int
    max_leaders_per_run: int
    network_read_requested: bool
    planned_endpoints: list[str]
    ready_for_bounded_read: bool
    issues: list[CopyPreflightIssue] = field(default_factory=list)


def run_copy_preflight(
    config: AppConfig,
    *,
    network_read: bool = False,
    max_leaders: int | None = None,
) -> CopyPreflightReport:
    path = shortlist_path(config)
    limit = max(1, max_leaders or config.copy_max_leaders_per_run)
    exists = path.exists()
    entries = load_shortlist_entries(path) if exists else []
    shortlisted = [entry for entry in entries if entry.status == LeaderStatus.SHORTLISTED]
    rejected = [entry for entry in entries if entry.status == LeaderStatus.REJECTED]
    issues: list[CopyPreflightIssue] = []
    if not exists:
        issues.append(CopyPreflightIssue("ERROR", "SOURCE_UNAVAILABLE", "Shortlist locale absente."))
    if not shortlisted:
        issues.append(CopyPreflightIssue("ERROR", "NO_SHORTLISTED_LEADERS", "Aucun leader shortlisté utilisable."))
    if len(shortlisted) > limit:
        issues.append(
            CopyPreflightIssue(
                "WARNING",
                "SHORTLIST_LIMIT_APPLIED",
                f"{len(shortlisted)} leaders shortlistés; le run sera borné aux {limit} premiers.",
            )
        )
    for entry in entries:
        if "..." in entry.wallet_address:
            issues.append(CopyPreflightIssue("ERROR", "TRUNCATED_ADDRESS_REJECTED", entry.wallet_address))
        elif not is_full_wallet_address(entry.wallet_address):
            issues.append(CopyPreflightIssue("ERROR", "INVALID_ADDRESS_REJECTED", entry.wallet_address))
    runtime = scan_runtime_files(config)
    if runtime.archive_files_at_root:
        issues.append(CopyPreflightIssue("WARNING", "ARCHIVE_DIRTY_ROOT_ZIP", "Archive ZIP/7Z/RAR détectée à la racine."))
    if runtime.logs_databases:
        issues.append(CopyPreflightIssue("WARNING", "LEGACY_DB_IN_LOGS", "DB legacy détectée dans logs/, exclue des archives."))
    if not network_read:
        issues.append(CopyPreflightIssue("INFO", "NETWORK_READ_DISABLED", "Préflight sans autorisation réseau; aucun appel /info ne sera lancé."))
    hard_errors = [issue for issue in issues if issue.level == "ERROR"]
    ready = network_read and not hard_errors and bool(shortlisted)
    return CopyPreflightReport(
        generated_at=utc_now(),
        shortlist_path=str(path),
        shortlist_exists=exists,
        total_entries=len(entries),
        shortlisted_entries=len(shortlisted),
        rejected_entries=len(rejected),
        leaders_planned=min(len(shortlisted), limit),
        max_leaders_per_run=limit,
        network_read_requested=network_read,
        planned_endpoints=[
            "allMids",
            "clearinghouseState",
            "userFillsByTime",
            "userFills",
            "openOrders",
            "frontendOpenOrders",
            "userFees",
            "userRateLimit",
        ],
        ready_for_bounded_read=ready,
        issues=issues,
    )


def write_copy_preflight_report(report: CopyPreflightReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "copy_preflight_report.json"
    md_path = output_dir / "copy_preflight_report.md"
    json_path.write_text(json.dumps(to_jsonable(report), indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(format_copy_preflight_report(report), encoding="utf-8")
    return json_path, md_path


def format_copy_preflight_report(report: CopyPreflightReport) -> str:
    lines = [
        "# HyperSmart copy preflight",
        "",
        "Mode: research/paper only. Aucun ordre, aucune signature, aucun mainnet.",
        "",
        f"- shortlist: `{report.shortlist_path}`",
        f"- entries: {report.total_entries}",
        f"- shortlisted: {report.shortlisted_entries}",
        f"- rejected: {report.rejected_entries}",
        f"- leaders planned: {report.leaders_planned}/{report.max_leaders_per_run}",
        f"- network read requested: {report.network_read_requested}",
        f"- ready for bounded read: {report.ready_for_bounded_read}",
        "",
        "## Planned /info payloads",
    ]
    lines.extend(f"- `{endpoint}`" for endpoint in report.planned_endpoints)
    lines.append("")
    lines.append("## Issues")
    if not report.issues:
        lines.append("- None")
    for issue in report.issues:
        lines.append(f"- {issue.level} `{issue.code}`: {issue.message}")
    return "\n".join(lines) + "\n"
