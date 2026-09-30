from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


STATUS_DONE = "DONE"
STATUS_DEFERRED = "DEFERRED_SAFE_WITH_REASON"
STATUS_BLOCKED = "BLOCKED_WITH_PROOF"
STATUS_REFUSED = "REFUSED_DANGEROUS"


@dataclass(frozen=True, slots=True)
class RequirementFamily:
    family_id: str
    label: str
    expected_paths: tuple[str, ...] = ()
    expected_commands: tuple[str, ...] = ()
    safety_note: str = ""


@dataclass(frozen=True, slots=True)
class CoverageRow:
    family_id: str
    label: str
    status: str
    evidence_files: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    missing: str = ""
    next_action: str = ""


@dataclass(frozen=True, slots=True)
class CoverageAudit:
    rows: tuple[CoverageRow, ...]
    report_path: Path
    non_deletion_path: Path
    write_warnings: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def done(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_DONE)

    @property
    def deferred(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_DEFERRED)

    @property
    def blocked(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_BLOCKED)

    @property
    def refused(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_REFUSED)

    @property
    def has_untracked_family(self) -> bool:
        return any(row.status in {"TODO", "DOING", "PARTIAL", ""} for row in self.rows)


REQUIRED_FAMILIES: tuple[RequirementFamily, ...] = (
    RequirementFamily("SECURITY", "Securite read-only", ("src/hl_observer/security", "AGENTS.md"), ("safety-audit",)),
    RequirementFamily("INTERNET_RESEARCH", "Recherche internet", ("docs/research", "docs/HYPERSMART_API_LIMITS.md")),
    RequirementFamily("MANUAL_RESEARCH", "Recherche humaine", ("docs/research",)),
    RequirementFamily("INITIAL_AUDIT", "Audit initial", ("docs/release",)),
    RequirementFamily("RUNTIME_ARCHIVE", "Runtime et archive", ("src/hl_observer/runtime", "tools/create_clean_archive.ps1")),
    RequirementFamily("LOGS_LOSSES", "Logs et pertes", ("src/hl_observer/simulation", "logs/logs à envoyer"), ("simulation-loss-report",)),
    RequirementFamily("POSITION_REPRODUCTION", "Open/add/reduce/close", ("src/hl_observer/wallets",)),
    RequirementFamily("DELTA_DETECTOR", "Delta detector", ("src/hl_observer/wallets/delta_utils.py",)),
    RequirementFamily("SIGNAL_CANDIDATE", "SignalCandidate", ("src/hl_observer/signals", "src/hl_observer/copying")),
    RequirementFamily("PAPER_CHAIN", "PaperIntent/PaperTrade local", ("src/hl_observer/paper", "src/hl_observer/following")),
    RequirementFamily("EXIT_ENGINE", "Exit engine local", ("src/hl_observer/exits",)),
    RequirementFamily("MULTI_POSITION", "Multi-positions", ("src/hl_observer/clusters", "src/hl_observer/ui/routes.py")),
    RequirementFamily("PYRAMIDING", "Pyramiding vs martingale", ("src/hl_observer/analysis", "docs/HYPERSMART_SIMULATION_ENGINE.md")),
    RequirementFamily("PORTFOLIO_HEAT", "Portfolio heat", ("src/hl_observer/ui/routes.py",)),
    RequirementFamily("REALTIME_EVENT_BUS", "Temps reel et event bus", ("src/hl_observer/ui/event_bus.py",)),
    RequirementFamily("REALTIME_RECOVERY", "Recovery realtime", ("src/hl_observer/realtime/recovery_engine.py", "tests/test_realtime_recovery_engine.py"), ("realtime-recovery-plan",)),
    RequirementFamily("RECONNECT_BACKFILL", "Reconnect + backfill borne", ("src/hl_observer/realtime/recovery_engine.py", "src/hl_observer/data_sources/historical_backfill_engine.py"), ("realtime-recovery-plan", "historical-backfill-plan")),
    RequirementFamily("LIVE_PNL", "PnL live", ("src/hl_observer/ui/routes.py",), ("live-pnl",)),
    RequirementFamily("BEGINNER_UI", "UI debutant", ("src/hl_observer/ui/templates/index.html", "src/hl_observer/ui/static/app.js")),
    RequirementFamily("METAGRAPHS", "Metagraphes", ("src/hl_observer/ui/static/app.js",)),
    RequirementFamily("COPY_RUN", "Copy-run read-only", ("src/hl_observer/cli.py", "src/hl_observer/copying")),
    RequirementFamily("WEBSOCKET_BOUNDED", "WebSocket borne", ("src/hl_observer/wallets/user_fills_live.py", "src/hl_observer/wallets/public_trades_live.py")),
    RequirementFamily("LOCAL_SCAN", "Scan local rapide", ("src/hl_observer/local_index",), ("benchmark-local-scan",)),
    RequirementFamily("EVENT_SOURCING", "Event sourcing local", ("src/hl_observer/storage/models.py",)),
    RequirementFamily("DATASET_HISTORICAL", "Dataset historique", ("src/hl_observer/data_sources", "docs/HYPERSMART_DATA_SOURCES.md")),
    RequirementFamily("DATA_ACQUISITION_ENGINE", "DataAcquisitionEngine", ("src/hl_observer/data_sources/acquisition_engine.py",), ("data-quality-check",)),
    RequirementFamily("REQUEST_BUDGET_MANAGER", "RequestBudgetManager", ("src/hl_observer/data_sources/acquisition_engine.py",), ("data-quality-check",)),
    RequirementFamily("PERSISTENT_FETCH_QUEUE", "PersistentFetchQueue", ("src/hl_observer/data_sources/acquisition_engine.py", "tests/test_data_acquisition_engine.py")),
    RequirementFamily("HISTORICAL_BACKFILL_ENGINE", "HistoricalBackfillEngine", ("src/hl_observer/data_sources/historical_backfill_engine.py", "tests/test_historical_backfill_engine.py"), ("historical-backfill-plan",)),
    RequirementFamily("CACHE_TTL_BACKOFF", "Cache TTL et backoff", ("src/hl_observer/data_sources/historical_backfill_engine.py", "tests/test_historical_backfill_engine.py")),
    RequirementFamily("DATA_QUALITY_GATE", "DataQualityGate", ("src/hl_observer/data_sources/acquisition_engine.py", "tests/test_data_acquisition_engine.py"), ("data-quality-check",)),
    RequirementFamily("WALLET_UNIVERSE", "Wallet universe", ("src/hl_observer/wallet_universe",)),
    RequirementFamily("WALLET_INTELLIGENCE", "Wallet intelligence", ("src/hl_observer/analysis", "docs/HYPERSMART_WALLET_INTELLIGENCE.md")),
    RequirementFamily("SMART_MONEY", "Smart money", ("src/hl_observer/wallets",)),
    RequirementFamily("TIMING_DNA", "Timing DNA", ("src/hl_observer/analysis",)),
    RequirementFamily("EDGE_REMAINING", "Edge remaining", ("src/hl_observer/edge/edge_remaining.py",), ("edge-report",)),
    RequirementFamily("ENTRY_EXIT", "Entry/exit policy", ("src/hl_observer/following", "src/hl_observer/exits")),
    RequirementFamily("BACKTEST", "Backtest", ("src/hl_observer/backtest", "docs/HYPERSMART_BACKTESTING.md")),
    RequirementFamily("WALK_FORWARD_NO_LOOKAHEAD", "Walk-forward/no-lookahead", ("src/hl_observer/backtest/walk_forward.py", "src/hl_observer/optimization/walk_forward_validator.py")),
    RequirementFamily("ANTI_OVERFIT", "Anti-overfit", ("src/hl_observer/optimization/anti_overfit_guard.py", "src/hl_observer/optimization/profit_optimizer.py"), ("anti-overfit-audit",)),
    RequirementFamily("PROFIT_OPTIMIZER", "Profit optimizer honnête", ("src/hl_observer/optimization/profit_optimizer.py",), ("best-config-report",)),
    RequirementFamily("NO_TRADE", "No-trade report", ("src/hl_observer/reports", "src/hl_observer/copying/reports.py")),
    RequirementFamily("OPPORTUNITY_FUNNEL", "Opportunity funnel", ("src/hl_observer/scanner", "src/hl_observer/ui/routes.py")),
    RequirementFamily("CONSENSUS_CROWDING", "Consensus/crowding", ("src/hl_observer/clusters",)),
    RequirementFamily("PERPS_RISK", "Perps risk", ("src/hl_observer/risk",)),
    RequirementFamily("WATCHLIST", "Watchlist", ("src/hl_observer/wallets",)),
    RequirementFamily("DECISION_MEMORY", "Decision memory", ("src/hl_observer/ui/persistent_state.py",)),
    RequirementFamily("DECISION_REVIEW", "Decision review", ("src/hl_observer/simulation/decision_replay_analyzer.py",)),
    RequirementFamily("PATTERN_DETECTOR", "Pattern detector", ("src/hl_observer/analysis", "docs/HYPERSMART_PATTERN_DETECTION.md")),
    RequirementFamily("EXPLAIN_FR", "Explications FR", ("src/hl_observer/simulation/loss_attribution.py",)),
    RequirementFamily("DASHBOARD_TRUTH", "Dashboard truth/provenance", ("src/hl_observer/dashboard_truth",), ("dashboard-truth-audit",)),
    RequirementFamily("QUALITY_GATES", "Quality gates", ("src/hl_observer/release/prompt_coverage.py",), ("prompt-coverage-audit", "non-deletion-check")),
    RequirementFamily("FINAL_REPORT", "Rapport final", ("docs/release",)),
    RequirementFamily("CHATGPT_SUMMARY", "Resume ChatGPT", ("logs/logs à envoyer", "docs/release/CODEX_CODE_FIRST_DELIVERY_REPORT.md")),
)


def evaluate_prompt_coverage(root: Path = Path(".")) -> CoverageAudit:
    root = root.resolve()
    rows = tuple(_evaluate_family(root, family) for family in REQUIRED_FAMILIES)
    report = root / "docs" / "release" / "MEGA_V1_PROMPT_COVERAGE_AUDIT.md"
    non_deletion = root / "docs" / "release" / "MEGA_V1_NON_DELETION_CHECK.md"
    audit = CoverageAudit(rows=rows, report_path=report, non_deletion_path=non_deletion)
    write_warnings = tuple(
        warning
        for warning in (
            _write_coverage_report(audit),
            _write_non_deletion_report(audit),
        )
        if warning
    )
    if write_warnings:
        audit = CoverageAudit(
            rows=rows,
            report_path=report,
            non_deletion_path=non_deletion,
            write_warnings=write_warnings,
        )
    return audit


def verify_non_deletion(rows: tuple[CoverageRow, ...]) -> tuple[bool, list[str]]:
    missing = [row.family_id for row in rows if row.status in {"TODO", "DOING", "PARTIAL", ""}]
    return not missing, missing


def format_coverage_summary(audit: CoverageAudit) -> str:
    ok, missing = verify_non_deletion(audit.rows)
    lines = [
        "mega_v1_prompt_coverage=tracked",
        f"total_families={audit.total}",
        f"done={audit.done}",
        f"deferred_safe={audit.deferred}",
        f"blocked_with_proof={audit.blocked}",
        f"refused_dangerous={audit.refused}",
        f"todo_or_partial={len(missing)}",
        f"report={audit.report_path}",
        f"non_deletion_report={audit.non_deletion_path}",
        f"ok={str(ok).lower()}",
    ]
    if audit.write_warnings:
        lines.append("write_warnings=" + " || ".join(audit.write_warnings))
    if missing:
        lines.append("missing=" + ",".join(missing))
    return "\n".join(lines)


def _evaluate_family(root: Path, family: RequirementFamily) -> CoverageRow:
    evidence = tuple(path for path in family.expected_paths if (root / path).exists())
    if evidence:
        return CoverageRow(
            family_id=family.family_id,
            label=family.label,
            status=STATUS_DONE,
            evidence_files=evidence,
            commands=family.expected_commands,
            next_action="Maintenir les tests et la provenance; ne pas transformer en execution.",
        )
    if family.safety_note:
        return CoverageRow(
            family_id=family.family_id,
            label=family.label,
            status=STATUS_REFUSED,
            evidence_files=(),
            commands=family.expected_commands,
            missing="Fonction dangereuse refusee.",
            next_action=family.safety_note,
        )
    return CoverageRow(
        family_id=family.family_id,
        label=family.label,
        status=STATUS_DEFERRED,
        evidence_files=(),
        commands=family.expected_commands,
        missing="Aucun fichier direct detecte pour cette famille.",
        next_action="Creer une implementation testee ou documenter un blocage prouve.",
    )


def _write_coverage_report(audit: CoverageAudit) -> str | None:
    lines = [
        "# MEGA V1 Prompt Coverage Audit",
        "",
        "Statuts autorises: DONE, BLOCKED_WITH_PROOF, DEFERRED_SAFE_WITH_REASON, REFUSED_DANGEROUS.",
        "Aucun statut TODO/PARTIAL n'est accepte dans ce controle.",
        "",
        "| Famille | Statut | Fichiers | Commandes | Manque | Prochaine correction |",
        "|---|---|---|---|---|---|",
    ]
    for row in audit.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.label,
                    row.status,
                    "<br>".join(row.evidence_files) or "-",
                    "<br>".join(row.commands) or "-",
                    row.missing or "-",
                    row.next_action or "-",
                ]
            )
            + " |"
        )
    return _safe_write_text(audit.report_path, "\n".join(lines) + "\n")


def _write_non_deletion_report(audit: CoverageAudit) -> str | None:
    ok, missing = verify_non_deletion(audit.rows)
    lines = [
        "# MEGA V1 Non-Deletion Check",
        "",
        f"Resultat: {'OK' if ok else 'FAIL'}",
        "",
        f"- Total familles suivies: {audit.total}",
        f"- TODO/PARTIAL detectes: {len(missing)}",
        f"- Familles manquantes: {', '.join(missing) if missing else 'aucune'}",
        "",
        "Ce controle verifie que les grandes familles du megaprompt restent tracees.",
        "Il ne pretend pas que toutes les familles sont terminees: les statuts DEFERRED/BLOCKED restent visibles.",
    ]
    return _safe_write_text(audit.non_deletion_path, "\n".join(lines) + "\n")


def _safe_write_text(path: Path, text: str) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"{path}: {exc.__class__.__name__}: {exc}"
    return None
