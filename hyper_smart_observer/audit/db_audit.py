from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.runtime.runtime_check import scan_runtime_files


def audit_databases(config: AppConfig) -> tuple[bool, str]:
    report = scan_runtime_files(config)
    configured_db = str(config.database_path).replace("\\", "/").lower()
    if "/logs/" in configured_db or configured_db.startswith("logs/"):
        return False, f"Configured HyperSmart DB is under logs: {config.database_path}"
    suffix = f" (scan bounded: {report.stopped_reason})" if report.stopped_reason else ""
    if report.logs_databases:
        return (
            True,
            f"Legacy DB(s) in logs detected and excluded from clean archives: {len(report.logs_databases)}{suffix}",
        )
    return True, f"No HyperSmart DB configured under logs; runtime DB files excluded from archives.{suffix}"
