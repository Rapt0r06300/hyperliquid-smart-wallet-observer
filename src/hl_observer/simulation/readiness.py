from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from hl_observer.config.settings import Settings
from hl_observer.runtime.write_diagnostics import check_runtime_write_readiness
from hl_observer.simulation.decision_replay_analyzer import (
    ReplayAnalysis,
    analyze_decision_logs_summary,
    default_logs_to_send_dir,
)
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.models import CollectionRun, PositionDeltaModel, TopWallet
from hl_observer.utils.time import now_ms


STATUS_ACTIVE = "SIMULATION_ACTIVE"
STATUS_OBSERVING = "OBSERVING_NO_VIRTUAL_ENTRY"
STATUS_WAITING_LEADERS = "WAITING_FOR_LEADERS"
STATUS_WAITING_FRESH_LEADERS = "WAITING_FOR_FRESH_LEADERS"
STATUS_WAITING_DELTAS = "WAITING_FOR_FRESH_DELTAS"
STATUS_WAITING_ENTRIES = "WAITING_FOR_FRESH_ENTRY_DELTAS"
STATUS_DB_BLOCKED = "BLOCKED_DB_NOT_WRITABLE"
STATUS_DB_UNREADABLE = "BLOCKED_DB_UNREADABLE"

ENTRY_PREFIXES = ("open", "add", "increase", "flip")


@dataclass(frozen=True, slots=True)
class SimulationReadinessReport:
    status: str
    database_url: str
    db_readable: bool
    db_writable: bool
    db_warning: str | None
    log_dir: Path
    log_writable: bool
    log_warning: str | None
    leaders_selected: int
    fresh_leaders_selected: int
    recent_deltas: int
    fresh_entry_deltas: int
    virtual_entries_logged: int
    virtual_refusals_logged: int
    top_refusal_reasons: tuple[tuple[str, int], ...]
    next_actions: tuple[str, ...] = field(default_factory=tuple)
    orders_created: int = 0
    real_orders_created: int = 0
    execution: str = "forbidden"
    research_only: bool = True


def build_simulation_readiness_report(
    settings: Settings,
    *,
    log_dir: Path | None = None,
    fresh_window_ms: int = 20_000,
    leader_fresh_window_ms: int = 5 * 60_000,
) -> SimulationReadinessReport:
    current_ms = now_ms()
    log_dir = log_dir or default_logs_to_send_dir()
    runtime_writes = check_runtime_write_readiness(log_dir, stale_after_seconds=60)
    analysis = analyze_decision_logs_summary(log_dir)
    db_readable = True
    db_writable = True
    db_warning: str | None = None
    counts: dict[str, int] = {
        "leaders_selected": 0,
        "fresh_leaders_selected": 0,
        "recent_deltas": 0,
        "fresh_entry_deltas": 0,
    }

    try:
        session_factory = create_session_factory(create_sqlite_engine(settings.database_url))
        with session_factory() as session:
            counts["leaders_selected"] = int(
                session.scalar(
                    select(func.count()).select_from(TopWallet).where(TopWallet.status == "selected")
                )
                or 0
            )
            counts["fresh_leaders_selected"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(TopWallet)
                    .where(TopWallet.status == "selected")
                    .where(TopWallet.selected_at_ms >= current_ms - max(1, leader_fresh_window_ms))
                )
                or 0
            )
            counts["recent_deltas"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PositionDeltaModel)
                    .where(
                        or_(
                            PositionDeltaModel.detected_at_ms >= current_ms - max(1, fresh_window_ms),
                            PositionDeltaModel.exchange_ts >= current_ms - max(1, fresh_window_ms),
                        )
                    )
                )
                or 0
            )
            counts["fresh_entry_deltas"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PositionDeltaModel)
                    .where(
                        or_(
                            PositionDeltaModel.detected_at_ms >= current_ms - max(1, fresh_window_ms),
                            PositionDeltaModel.exchange_ts >= current_ms - max(1, fresh_window_ms),
                        )
                    )
                    .where(
                        or_(
                            *[
                                func.lower(PositionDeltaModel.delta_type).like(f"{prefix}%")
                                for prefix in ENTRY_PREFIXES
                            ],
                            *[
                                func.lower(PositionDeltaModel.action).like(f"{prefix}%")
                                for prefix in ENTRY_PREFIXES
                            ],
                        )
                    )
                )
                or 0
            )
            db_writable, db_warning = _probe_db_write(session)
    except SQLAlchemyError as exc:
        db_readable = False
        db_writable = False
        db_warning = f"{exc.__class__.__name__}: {exc}"

    status, next_actions = _status_and_actions(
        db_readable=db_readable,
        db_writable=db_writable,
        counts=counts,
        analysis=analysis,
    )
    return SimulationReadinessReport(
        status=status,
        database_url=settings.database_url,
        db_readable=db_readable,
        db_writable=db_writable,
        db_warning=db_warning,
        log_dir=log_dir,
        log_writable=runtime_writes.directory_write_probe_ok,
        log_warning=runtime_writes.directory_warning,
        leaders_selected=counts["leaders_selected"],
        fresh_leaders_selected=counts["fresh_leaders_selected"],
        recent_deltas=counts["recent_deltas"],
        fresh_entry_deltas=counts["fresh_entry_deltas"],
        virtual_entries_logged=analysis.accepted_count,
        virtual_refusals_logged=analysis.refused_count,
        top_refusal_reasons=analysis.top_refusal_reasons[:8],
        next_actions=tuple(next_actions),
    )


def format_simulation_readiness(report: SimulationReadinessReport) -> str:
    lines = [
        "simulation_readiness=paper_read_only",
        f"status={report.status}",
        f"database_url={report.database_url}",
        f"db_readable={str(report.db_readable).lower()}",
        f"db_writable={str(report.db_writable).lower()}",
        f"log_dir={report.log_dir}",
        f"log_writable={str(report.log_writable).lower()}",
        f"leaders_selected={report.leaders_selected}",
        f"fresh_leaders_selected={report.fresh_leaders_selected}",
        f"recent_deltas={report.recent_deltas}",
        f"fresh_entry_deltas={report.fresh_entry_deltas}",
        f"virtual_entries_logged={report.virtual_entries_logged}",
        f"virtual_position_actions_logged={report.virtual_entries_logged}",
        f"virtual_refusals_logged={report.virtual_refusals_logged}",
        f"orders_created={report.orders_created}",
        f"real_orders_created={report.real_orders_created}",
        "simulation_positions_are_virtual=true",
        f"execution={report.execution}",
        f"research_only={str(report.research_only).lower()}",
    ]
    if report.db_warning:
        lines.append(f"db_warning={_single_line(report.db_warning)}")
    if report.log_warning:
        lines.append(f"log_warning={_single_line(report.log_warning)}")
    if report.top_refusal_reasons:
        lines.append("top_refusal_reasons:")
        lines.extend(f"- {reason}: {count}" for reason, count in report.top_refusal_reasons)
    if report.next_actions:
        lines.append("next_actions:")
        lines.extend(f"- {action}" for action in report.next_actions)
    return "\n".join(lines)


def _probe_db_write(session: Any) -> tuple[bool, str | None]:
    marker = now_ms()
    try:
        probe = CollectionRun(
            started_at_ms=marker,
            finished_at_ms=marker,
            mode="simulation-readiness-probe",
            success=True,
            errors_count=0,
            wallets_count=0,
            coins_count=0,
            notes="rolled back diagnostic write probe",
        )
        session.add(probe)
        session.flush()
        session.rollback()
        return True, None
    except SQLAlchemyError as exc:
        session.rollback()
        return False, f"{exc.__class__.__name__}: {exc}"


def _status_and_actions(
    *,
    db_readable: bool,
    db_writable: bool,
    counts: dict[str, int],
    analysis: ReplayAnalysis,
) -> tuple[str, list[str]]:
    if not db_readable:
        return STATUS_DB_UNREADABLE, [
            "Verifier HL_DATABASE_URL et relancer LANCER_HYPERSMART.cmd pour recreer une DB de session propre.",
        ]
    if not db_writable:
        return STATUS_DB_BLOCKED, [
            "Utiliser la DB runtime de session du lanceur; fermer les anciens processus qui tiennent l'ancienne DB.",
        ]
    if counts["leaders_selected"] <= 0:
        return STATUS_WAITING_LEADERS, [
            "Laisser live-public-scan decouvrir/promouvoir des wallets complets, ou importer une shortlist propre.",
            "Le scanner peut tourner, mais il n'a encore aucun leader a suivre.",
        ]
    if counts["fresh_leaders_selected"] <= 0:
        return STATUS_WAITING_FRESH_LEADERS, [
            "Les leaders existent mais sont anciens; relancer le lanceur pour utiliser la DB runtime de session.",
            "Laisser live-public-scan et live-user-fills-scan rafraichir la shortlist avant toute position virtuelle.",
        ]
    if counts["recent_deltas"] <= 0:
        return STATUS_WAITING_DELTAS, [
            "Laisser live-user-fills-scan tourner sur la shortlist; aucun delta frais n'est encore stocke.",
            "Verifier que --network-read est actif et que la DB de session est inscriptible.",
        ]
    if counts["fresh_entry_deltas"] <= 0:
        return STATUS_WAITING_ENTRIES, [
            "Les deltas recents sont surtout reduce/close/data; attendre de vraies ouvertures/augmentations fraiches.",
        ]
    if analysis.accepted_count <= 0:
        reasons = ", ".join(reason for reason, _ in analysis.top_refusal_reasons[:3]) or "aucun log de decision"
        return STATUS_OBSERVING, [
            f"Le moteur observe mais refuse les entrees virtuelles; principales raisons: {reasons}.",
            "Analyser edge_remaining, fraicheur, consensus, liquidite et couts avant d'assouplir un seuil.",
        ]
    return STATUS_ACTIVE, [
        "Positions virtuelles presentes dans les logs; surveiller PnL net, drawdown, frais et raisons de sortie.",
    ]


def _single_line(value: str) -> str:
    return " ".join(str(value).split())
