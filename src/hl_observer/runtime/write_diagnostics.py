from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import time
from uuid import uuid4


RUNTIME_WRITE_OK = "OK"
RUNTIME_WRITE_WARN = "WARN"
RUNTIME_WRITE_BLOCKED = "BLOCKED_WITH_PROOF"

DEFAULT_RUNTIME_TARGETS = (
    "simulation_decisions_append_only.jsonl",
    "simulation_decisions_latest.jsonl",
    "simulation_pnl_ledger_latest.jsonl",
    "simulation_snapshot_latest.json",
    "simulation_export_state.json",
    "simulation_resume_pour_chatgpt.md",
    "cli_simulation_decisions_latest.jsonl",
    "cli_simulation_snapshot_latest.json",
    "cli_simulation_resume_pour_chatgpt.md",
    "realtime_replay_latest.jsonl",
    "realtime_replay_state.json",
)


@dataclass(frozen=True, slots=True)
class RuntimeWriteTarget:
    path: Path
    exists: bool
    size_bytes: int | None
    age_seconds: float | None
    append_probe_ok: bool
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeWriteReadinessReport:
    log_dir: Path
    directory_exists: bool
    directory_write_probe_ok: bool
    directory_warning: str | None
    targets: tuple[RuntimeWriteTarget, ...]
    stale_after_seconds: int
    status: str
    reason: str
    read_only_trading: bool = True
    deletes_only_own_probe: bool = True

    @property
    def blocked_targets(self) -> tuple[RuntimeWriteTarget, ...]:
        return tuple(target for target in self.targets if target.exists and not target.append_probe_ok)

    @property
    def stale_targets(self) -> tuple[RuntimeWriteTarget, ...]:
        return tuple(
            target
            for target in self.targets
            if target.age_seconds is not None and target.age_seconds > self.stale_after_seconds
        )


def check_runtime_write_readiness(
    log_dir: Path,
    *,
    stale_after_seconds: int = 60,
    target_names: tuple[str, ...] = DEFAULT_RUNTIME_TARGETS,
) -> RuntimeWriteReadinessReport:
    """Check whether the local simulation log/replay folder can be refreshed.

    This is not a process killer and not a cleanup command. It writes and removes
    one short-lived probe file in the target directory, then opens existing known
    runtime outputs in append mode without appending bytes. On Windows this is
    enough to surface many exclusive locks while preserving the log contents.
    """

    log_dir = log_dir.resolve()
    directory_exists = log_dir.exists() and log_dir.is_dir()
    directory_probe_ok = False
    directory_warning = None
    if directory_exists:
        directory_probe_ok, directory_warning = _probe_directory_writable(log_dir)
    else:
        directory_warning = "LOG_DIR_MISSING"

    targets = tuple(_inspect_target(log_dir / name) for name in target_names)
    blocked = tuple(target for target in targets if target.exists and not target.append_probe_ok)
    stale = tuple(
        target
        for target in targets
        if target.age_seconds is not None and target.age_seconds > stale_after_seconds
    )
    if not directory_exists or not directory_probe_ok:
        status = RUNTIME_WRITE_BLOCKED
        reason = directory_warning or "LOG_DIR_NOT_WRITABLE"
    elif blocked:
        status = RUNTIME_WRITE_BLOCKED
        names = ", ".join(target.path.name for target in blocked[:5])
        reason = f"RUNTIME_OUTPUT_LOCKED_OR_NOT_WRITABLE: {names}"
    elif stale:
        status = RUNTIME_WRITE_WARN
        names = ", ".join(target.path.name for target in stale[:5])
        reason = f"RUNTIME_OUTPUTS_STALE: {names}"
    else:
        status = RUNTIME_WRITE_OK
        reason = "runtime log/replay outputs are writable or ready to be created"
    return RuntimeWriteReadinessReport(
        log_dir=log_dir,
        directory_exists=directory_exists,
        directory_write_probe_ok=directory_probe_ok,
        directory_warning=directory_warning,
        targets=targets,
        stale_after_seconds=max(1, int(stale_after_seconds)),
        status=status,
        reason=reason,
    )


def format_runtime_write_readiness(report: RuntimeWriteReadinessReport) -> str:
    lines = [
        "runtime_write_check=local_simulation_outputs",
        f"log_dir={report.log_dir}",
        f"directory_exists={str(report.directory_exists).lower()}",
        f"directory_write_probe_ok={str(report.directory_write_probe_ok).lower()}",
        f"status={report.status}",
        f"reason={report.reason}",
        f"stale_after_seconds={report.stale_after_seconds}",
        f"blocked_targets={len(report.blocked_targets)}",
        f"stale_targets={len(report.stale_targets)}",
        f"read_only_trading={str(report.read_only_trading).lower()}",
        "orders_created=0",
        "processes_killed=0",
    ]
    if report.directory_warning:
        lines.append(f"directory_warning={report.directory_warning}")
    for target in report.targets:
        if target.exists or target.warning:
            age = "none" if target.age_seconds is None else f"{target.age_seconds:.3f}"
            lines.append(
                "target="
                + "|".join(
                    [
                        target.path.name,
                        f"exists={str(target.exists).lower()}",
                        f"size={target.size_bytes}",
                        f"age_seconds={age}",
                        f"append_probe_ok={str(target.append_probe_ok).lower()}",
                        f"warning={target.warning or 'none'}",
                    ]
                )
            )
    if report.status != RUNTIME_WRITE_OK:
        lines.append(
            "recommendation=fermer proprement le lanceur/serveur qui tient ces fichiers, puis relancer LANCER_HYPERSMART.cmd; ne pas tuer de processus automatiquement"
        )
    return "\n".join(lines)


def _inspect_target(path: Path) -> RuntimeWriteTarget:
    exists = path.exists()
    size = None
    age = None
    warning = None
    append_ok = True
    if exists:
        try:
            stat = path.stat()
            size = stat.st_size
            age = max(0.0, time() - stat.st_mtime)
        except OSError as exc:
            append_ok = False
            warning = f"{exc.__class__.__name__}: {exc}"
        if warning is None:
            append_ok, warning = _probe_existing_file_appendable(path)
    return RuntimeWriteTarget(
        path=path,
        exists=exists,
        size_bytes=size,
        age_seconds=round(age, 3) if age is not None else None,
        append_probe_ok=append_ok,
        warning=warning,
    )


def _probe_directory_writable(path: Path) -> tuple[bool, str | None]:
    probe = path / f".hypersmart_write_probe_{uuid4().hex}.tmp"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"{exc.__class__.__name__}: {exc}"
    return True, None


def _probe_existing_file_appendable(path: Path) -> tuple[bool, str | None]:
    try:
        with path.open("ab") as handle:
            handle.write(b"")
    except OSError as exc:
        return False, f"{exc.__class__.__name__}: {exc}"
    return True, None
