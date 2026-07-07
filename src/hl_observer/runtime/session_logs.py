from __future__ import annotations

import json
import shutil
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:  # Python 3.11+
    from datetime import UTC
except ImportError:  # Python 3.10 fallback
    UTC = timezone.utc
from typing import Iterable


CANONICAL_LOGS_TO_SEND_DIRNAME = "logs \u00e0 envoyer"
MOJIBAKE_LOGS_TO_SEND_DIRNAME = "logs \u00c3\u00a0 envoyer"

ACTIVE_SESSION_FILES = (
    "simulation_decisions_append_only.jsonl",
    "simulation_decisions_latest.jsonl",
    "simulation_pnl_ledger_latest.jsonl",
    "simulation_snapshot_latest.json",
    "simulation_export_state.json",
    "simulation_resume_pour_chatgpt.md",
    "simulation_log_summary_cache.json",
    "cli_simulation_decisions_latest.jsonl",
    "cli_simulation_snapshot_latest.json",
    "cli_simulation_resume_pour_chatgpt.md",
    "realtime_replay_latest.jsonl",
    "realtime_replay_state.json",
    "hypersmart_observer.log",
    "hypersmart_ia_explanations.json",
    "hypersmart_ia_history.jsonl",
    "hypersmart_ia_report.json",
    "hypersmart_ia_train.log",
    "simulation_fusion_runtime_latest.json",
    "wallet_mirror_journal.jsonl",
    "latest_loop_result.json",
    "latest_decision_trace.json",
    "latest_loop_input_diagnostics.json",
    "latest_loop_report.md",
    "SESSION_MANIFEST.json",
    "SESSION_MANIFEST.md",
)

FRESH_TEXT_FILES = {
    "simulation_decisions_append_only.jsonl": "",
    "simulation_decisions_latest.jsonl": "",
    "simulation_pnl_ledger_latest.jsonl": "",
    "cli_simulation_decisions_latest.jsonl": "",
    "realtime_replay_latest.jsonl": "",
    "simulation_resume_pour_chatgpt.md": "# HyperSmart simulation - session fraiche\n\nAucune decision exportee pour cette nouvelle session.\n",
    "cli_simulation_resume_pour_chatgpt.md": "# HyperSmart CLI simulation - session fraiche\n\nAucune decision CLI exportee pour cette nouvelle session.\n",
    "latest_loop_report.md": "# HyperSmart loop - session fraiche\n\nAucune boucle decision/testnet exportee pour cette nouvelle session.\n",
}

FRESH_JSON_FILES = {
    "simulation_snapshot_latest.json": {
        "session_status": "fresh",
        "message": "Nouvelle session; aucun evenement paper exporte pour le moment.",
        "execution": "forbidden",
        "paper_local_only": True,
    },
    "simulation_export_state.json": {"exported_event_keys": []},
    "simulation_log_summary_cache.json": {
        "version": 2,
        "event_count": 0,
        "accepted_count": 0,
        "refused_count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "total_estimated_pnl_usdc": 0.0,
        "total_fees_usdc": 0.0,
        "top_refusal_reasons": [],
        "signature": {"fresh_session": True},
    },
    "cli_simulation_snapshot_latest.json": {
        "session_status": "fresh",
        "message": "Nouvelle session CLI; aucun evenement exporte pour le moment.",
        "execution": "forbidden",
        "paper_local_only": True,
    },
    "realtime_replay_state.json": {
        "session_status": "fresh",
        "message": "Replay temps reel pret pour les prochains evenements.",
        "execution": "forbidden",
    },
    "latest_loop_result.json": {
        "session_status": "fresh",
        "message": "Nouvelle session; aucune boucle decision/testnet exportee pour le moment.",
        "execution": "forbidden",
        "mainnet_readonly": True,
        "testnet_locked": True,
    },
    "latest_decision_trace.json": [],
    "latest_loop_input_diagnostics.json": {
        "session_status": "fresh",
        "status": "EMPTY",
        "message": "Nouvelle session; aucun diagnostic d'entree loop pour le moment.",
        "execution": "forbidden",
    },
}


@dataclass(frozen=True, slots=True)
class PreparedSessionLogs:
    session_id: str
    log_dir: Path
    archive_dir: Path
    archived_files: tuple[Path, ...]
    fresh_files: tuple[Path, ...]
    warnings: tuple[str, ...]
    manifest_json: Path
    manifest_markdown: Path


def default_logs_to_send_dir(root: Path = Path(".")) -> Path:
    return root / "logs" / CANONICAL_LOGS_TO_SEND_DIRNAME


def prepare_fresh_simulation_logs(root: Path = Path("."), *, dry_run: bool = False) -> PreparedSessionLogs:
    """Start a fresh evidence bundle for one local simulation session.

    No file is deleted. Previous active evidence files and top-level archive_*
    files are moved under logs/logs a envoyer/_archives/session_*. Runtime DBs,
    WAL/SHM files and zip/7z/rar files are never copied into the fresh active
    bundle. This keeps ChatGPT/Codex analysis focused on the current session.
    """

    root = Path(root)
    logs_root = root / "logs"
    log_dir = default_logs_to_send_dir(root)
    session_id = datetime.now(UTC).strftime("session_%Y%m%d_%H%M%S")
    archive_dir = log_dir / "_archives" / session_id
    warnings: list[str] = []
    archived: list[Path] = []
    fresh: list[Path] = []

    if not dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)

    alias_dir = logs_root / MOJIBAKE_LOGS_TO_SEND_DIRNAME
    candidates: list[Path] = []
    if log_dir.exists():
        candidates.extend(_top_level_session_files(log_dir))
    if alias_dir.exists() and alias_dir != log_dir:
        alias_archive = archive_dir / "legacy_mojibake_logs_dir"
        for item in _top_level_session_files(alias_dir):
            candidates.append(item)
        if not dry_run:
            alias_archive.mkdir(parents=True, exist_ok=True)

    for path in candidates:
        if not path.exists():
            continue
        if not _is_safe_to_archive(path):
            warnings.append(f"skipped_runtime_or_archive={path}")
            continue
        destination_base = _destination_for(path, log_dir=log_dir, alias_dir=alias_dir, archive_dir=archive_dir)
        destination = _unique_destination(destination_base)
        if dry_run:
            archived.append(destination)
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
            archived.append(destination)
        except OSError as exc:
            warnings.append(f"archive_failed={path}: {exc.__class__.__name__}: {exc}")

    if not dry_run:
        for name, text in FRESH_TEXT_FILES.items():
            path = log_dir / name
            path.write_text(text, encoding="utf-8")
            fresh.append(path)
        for name, payload in FRESH_JSON_FILES.items():
            path = log_dir / name
            if isinstance(payload, dict):
                enriched = {
                    **payload,
                    "session_id": session_id,
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                }
            else:
                enriched = payload
            path.write_text(json.dumps(enriched, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
            fresh.append(path)
    else:
        fresh = [log_dir / name for name in (*FRESH_TEXT_FILES.keys(), *FRESH_JSON_FILES.keys())]

    manifest = {
        "session_id": session_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "log_dir": str(log_dir),
        "archive_dir": str(archive_dir),
        "archived_files": [str(path) for path in archived],
        "fresh_files": [str(path) for path in fresh],
        "warnings": warnings,
        "execution": "forbidden",
        "paper_local_only": True,
        "no_real_orders": True,
        "purpose": "current-session evidence bundle for ChatGPT/Codex debugging",
    }
    manifest_json = log_dir / "SESSION_MANIFEST.json"
    manifest_markdown = log_dir / "SESSION_MANIFEST.md"
    if not dry_run:
        manifest_json.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        manifest_markdown.write_text(_render_manifest_markdown(manifest), encoding="utf-8")
    return PreparedSessionLogs(
        session_id=session_id,
        log_dir=log_dir,
        archive_dir=archive_dir,
        archived_files=tuple(archived),
        fresh_files=tuple(fresh),
        warnings=tuple(warnings),
        manifest_json=manifest_json,
        manifest_markdown=manifest_markdown,
    )


def format_prepared_session_logs(result: PreparedSessionLogs) -> str:
    lines = [
        "simulation_logs_prepare=fresh_session",
        f"session_id={result.session_id}",
        f"log_dir={result.log_dir}",
        f"archive_dir={result.archive_dir}",
        f"archived_files={len(result.archived_files)}",
        f"fresh_files={len(result.fresh_files)}",
        f"warnings={len(result.warnings)}",
        f"manifest_json={result.manifest_json}",
        f"manifest_markdown={result.manifest_markdown}",
        "execution=forbidden",
        "paper_local_only=true",
    ]
    for warning in result.warnings[:20]:
        lines.append(f"warning={warning}")
    return "\n".join(lines)


def _top_level_session_files(log_dir: Path) -> Iterable[Path]:
    for item in log_dir.iterdir():
        if item.name == "_archives":
            continue
        if item.is_dir():
            continue
        if (
            item.name in ACTIVE_SESSION_FILES
            or item.name.startswith("archive_")
            or item.name.startswith(".hypersmart_")
            or (item.name.startswith("qa_observation_") and item.suffix.lower() == ".jsonl")
        ):
            yield item


def _is_safe_to_archive(path: Path) -> bool:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".db-wal", ".db-shm")):
        return False
    if suffixes.endswith((".zip", ".7z", ".rar")):
        return False
    return True


def _destination_for(path: Path, *, log_dir: Path, alias_dir: Path, archive_dir: Path) -> Path:
    if alias_dir.exists():
        try:
            path.relative_to(alias_dir)
            return archive_dir / "legacy_mojibake_logs_dir" / path.name
        except ValueError:
            pass
    if path.name.startswith("archive_") and len(path.name) > 160:
        digest = sha256(path.name.encode("utf-8", errors="replace")).hexdigest()[:16]
        suffix = path.suffix or ".log"
        return archive_dir / "legacy_long_archive_names" / f"legacy_archive_{digest}{suffix}"
    return archive_dir / path.name


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(1, 10_000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}_{datetime.now(UTC).timestamp():.0f}{suffix}"


def _render_manifest_markdown(manifest: dict[str, object]) -> str:
    archived = manifest.get("archived_files") or []
    fresh = manifest.get("fresh_files") or []
    warnings = manifest.get("warnings") or []
    lines = [
        "# HyperSmart logs a envoyer - session fraiche",
        "",
        f"- Session: `{manifest['session_id']}`",
        f"- Dossier actif: `{manifest['log_dir']}`",
        f"- Archive locale: `{manifest['archive_dir']}`",
        f"- Fichiers archives: {len(archived)}",
        f"- Fichiers frais crees: {len(fresh)}",
        f"- Warnings: {len(warnings)}",
        "",
        "Ces fichiers representent uniquement la session de simulation locale en cours.",
        "Aucun ordre reel, aucune signature, aucune cle privee.",
        "",
        "## Fichiers actifs",
    ]
    for path in fresh:
        lines.append(f"- `{Path(str(path)).name}`")
    if warnings:
        lines.extend(["", "## Avertissements"])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# V14 — Purge of stale/heavy TOP-LEVEL logs at each launch (user request:
# "les logs doivent etre remis a zero a chaque ouverture, SAUF l'intelligence
# de l'IA qui ne doit pas etre degradee"). The AI *intelligence* (trained model
# + training_samples.jsonl) lives under runtime/, which this function NEVER
# touches: it operates strictly inside logs/. Rolling *.log files are truncated
# to 0 bytes (handles stay valid for the processes that re-open them); heavy
# stale archives (*.zip/*.7z/*.rar) and the legacy mojibake dir are removed.
# SQLite/DB files are preserved (handled by reset-simulation-state, not logs).
# ---------------------------------------------------------------------------

_PRESERVE_DB_SUFFIXES = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".db-wal", ".db-shm")
_HEAVY_ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".gz", ".tar")


@dataclass(frozen=True, slots=True)
class PurgedLogs:
    logs_root: Path
    truncated: tuple[Path, ...]
    deleted: tuple[Path, ...]
    preserved: tuple[Path, ...]
    freed_bytes: int
    warnings: tuple[str, ...]


def _size_of(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def purge_stale_top_level_logs(root: Path = Path("."), *, dry_run: bool = False) -> PurgedLogs:
    """Reset the bloated logs/ directory while protecting AI intelligence + DBs.

    Only the *top level* of logs/ is affected. Sub-directories (notably the active
    "logs a envoyer" evidence bundle, prepared separately) are left untouched.
    runtime/ (model + training samples) is outside logs/ and never touched here.
    """
    root = Path(root)
    logs_root = root / "logs"
    truncated: list[Path] = []
    deleted: list[Path] = []
    preserved: list[Path] = []
    warnings: list[str] = []
    freed = 0

    if not logs_root.exists():
        return PurgedLogs(logs_root, (), (), (), 0, ("logs_dir_absent",))

    for item in sorted(logs_root.iterdir()):
        try:
            if item.is_dir():
                # Remove only the legacy mojibake duplicate dir; keep every other dir
                # (the canonical "logs a envoyer" bundle + structured/ are preserved).
                if item.name == MOJIBAKE_LOGS_TO_SEND_DIRNAME:
                    freed += sum(_size_of(p) for p in item.rglob("*") if p.is_file())
                    if not dry_run:
                        shutil.rmtree(item, ignore_errors=True)
                    deleted.append(item)
                else:
                    preserved.append(item)
                continue

            suffixes = "".join(item.suffixes).lower()
            if suffixes.endswith(_PRESERVE_DB_SUFFIXES):
                preserved.append(item)            # runtime DB / event log — keep
                continue
            if item.name.endswith(".lock"):
                preserved.append(item)            # active lock file — leave alone
                continue

            if item.name.endswith(".log") or item.name.endswith(".out.log") or item.name.endswith(".err.log"):
                size = _size_of(item)
                if size > 0:
                    freed += size
                    if not dry_run:
                        # Truncate in place: empties the file, keeps the inode/handle valid.
                        with open(item, "w", encoding="utf-8"):
                            pass
                    truncated.append(item)
                else:
                    preserved.append(item)
                continue

            if suffixes.endswith(_HEAVY_ARCHIVE_SUFFIXES):
                freed += _size_of(item)
                if not dry_run:
                    item.unlink(missing_ok=True)
                deleted.append(item)
                continue

            preserved.append(item)                # unknown file type — be conservative
        except OSError as exc:
            warnings.append(f"purge_failed={item.name}: {exc.__class__.__name__}: {exc}")

    return PurgedLogs(
        logs_root=logs_root,
        truncated=tuple(truncated),
        deleted=tuple(deleted),
        preserved=tuple(preserved),
        freed_bytes=int(freed),
        warnings=tuple(warnings),
    )


def format_purged_logs(result: PurgedLogs) -> str:
    mb = result.freed_bytes / (1024 * 1024)
    lines = [
        "logs_purge=top_level_reset",
        f"logs_root={result.logs_root}",
        f"truncated={len(result.truncated)}",
        f"deleted={len(result.deleted)}",
        f"preserved={len(result.preserved)}",
        f"freed_mb={mb:.1f}",
        "ai_intelligence_preserved=true (runtime/ model + training_samples untouched)",
        f"warnings={len(result.warnings)}",
    ]
    for warning in result.warnings[:20]:
        lines.append(f"warning={warning}")
    return "\n".join(lines)
