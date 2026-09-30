"""Compact, local-only resume context for Codex Discovery V3.2."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hl_observer.research.hypothesis_ledger import FAMILIES, compact_status, load_records
from hl_observer.research.process_memory import (
    combine_process_records,
    load_process_records,
    process_memory_summary,
)

DEFAULT_LEDGER = Path("runtime/codex_research/HYPOTHESIS_LEDGER.jsonl")
DEFAULT_PROCESS_MEMORY = Path("runtime/codex_research/PROCESS_MEMORY.jsonl")
HISTORICAL_PROCESS_MEMORY = Path("docs/quant/HISTORICAL_EXPERIMENT_MEMORY.jsonl")
SEMANTIC_STATUS = Path("runtime/codex_research/SEMANTIC_DISCOVERY_STATUS.json")
_FAMILY_ORDER = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")
_DATA_HINTS = (
    "data/bbo_synchro.jsonl",
    "runtime/data/bbo_synchro.jsonl",
    "runtime/bbo_synchro.jsonl",
    "runtime/codex_research/HYPOTHESIS_LEDGER.jsonl",
    "runtime/codex_research/PROCESS_MEMORY.jsonl",
    "runtime/copy_vault",
    "runtime/lead_lag",
    "runtime/cross_venue",
)
_BBO_HINTS = frozenset(
    {
        "data/bbo_synchro.jsonl",
        "runtime/data/bbo_synchro.jsonl",
        "runtime/bbo_synchro.jsonl",
    }
)
_BBO_MAX_AGE_SECONDS = 300.0


def _git_dir(repo_root: Path) -> Path | None:
    marker = repo_root / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        text = marker.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            raw = text.split(":", 1)[1].strip()
            path = Path(raw)
            return path if path.is_absolute() else (repo_root / path).resolve()
    return None


def _common_git_dir(git_dir: Path) -> Path:
    marker = git_dir / "commondir"
    if not marker.exists():
        return git_dir
    raw = marker.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return git_dir
    path = Path(raw)
    return path if path.is_absolute() else (git_dir / path).resolve()


def _valid_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value)


def _read_ref_from_dir(directory: Path, ref: str) -> str | None:
    ref_path = directory / ref
    if ref_path.exists():
        value = ref_path.read_text(encoding="utf-8", errors="replace").strip()
        if _valid_sha(value):
            return value.lower()
    packed = directory / "packed-refs"
    if packed.exists():
        for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(("#", "^")):
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref and _valid_sha(parts[0]):
                return parts[0].lower()
    return None


def _read_head(repo_root: Path) -> str:
    git_dir = _git_dir(repo_root)
    if git_dir is None:
        return "UNKNOWN"
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return "UNKNOWN"
    head = head_path.read_text(encoding="utf-8", errors="replace").strip()
    if _valid_sha(head):
        return head.lower()
    if not head.startswith("ref:"):
        return "UNKNOWN"
    ref = head.split(":", 1)[1].strip()
    common_dir = _common_git_dir(git_dir)
    for directory in dict.fromkeys((git_dir, common_dir)):
        resolved = _read_ref_from_dir(directory, ref)
        if resolved is not None:
            return resolved
    return "UNKNOWN"


def read_repository_head(repo_root: str | Path) -> str:
    """Read the exact local repository HEAD without invoking git or the network."""
    return _read_head(Path(repo_root).resolve())


def _resolve(repo_root: Path, value: str | Path | None, default: Path) -> Path:
    path = Path(value) if value is not None else default
    return path if path.is_absolute() else repo_root / path


def _select_family(records: list[dict[str, Any]]) -> str:
    ranked: list[tuple[int, int, int, int, str]] = []
    for index, family in enumerate(_FAMILY_ORDER):
        status = compact_status(records, family=family)
        ranked.append(
            (
                int(status["trial_count"]),
                int(status["unique_hypotheses"]),
                int(status["records"]),
                index,
                family,
            )
        )
    return min(ranked)[-1]


def _next_actions(status: dict[str, Any]) -> list[str]:
    if status["records"] == 0:
        return ["establish_baseline", "generate_semantic_shortlist"]
    if status["rediscovery_required"]:
        return ["pivot_semantic_discovery", "generate_semantic_shortlist"]
    if status["challenger_required"]:
        return ["run_champion_challenger", "generate_semantic_shortlist"]
    return ["continue_v31_controller", "generate_semantic_shortlist"]


def _semantic_status(repo_root: Path, family: str, head: str) -> dict[str, Any]:
    path = repo_root / SEMANTIC_STATUS
    empty = {
        "available": False,
        "family": family,
        "generated": 0,
        "shortlisted": 0,
        "filtered_before_llm": 0,
    }
    if not path.exists() or head == "UNKNOWN":
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 2
        or payload.get("head") != head
        or not isinstance(payload.get("families"), dict)
    ):
        return empty
    family_payload = payload["families"].get(family)
    if not isinstance(family_payload, dict) or family_payload.get("family") != family:
        return empty

    values: dict[str, int] = {}
    for key in ("generated", "shortlisted", "filtered_before_llm"):
        value = family_payload.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return empty
        values[key] = value
    return {"available": True, "family": family, **values}


def _last_nonblank_json_object(path: Path) -> bool:
    """Validate only the bounded JSONL tail so large captures stay cheap to inspect."""
    try:
        size = path.stat().st_size
        if size <= 0:
            return False
        with path.open("rb") as handle:
            handle.seek(max(0, size - 8192))
            tail = handle.read().decode("utf-8", errors="replace").splitlines()
        last = next((line.strip() for line in reversed(tail) if line.strip()), None)
        if last is None:
            return False
        return isinstance(json.loads(last), dict)
    except (OSError, json.JSONDecodeError):
        return False


def _fresh_bbo_hint(path: Path, *, now: float | None = None) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    if not path.is_file() or stat.st_size <= 0:
        return False
    current = time.time() if now is None else now
    age = current - stat.st_mtime
    if age < -5.0 or age > _BBO_MAX_AGE_SECONDS:
        return False
    return _last_nonblank_json_object(path)


def _data_surface_hints(root: Path) -> list[str]:
    hints: list[str] = []
    for item in _DATA_HINTS:
        target = root / item
        if item in _BBO_HINTS:
            if _fresh_bbo_hint(target):
                hints.append(item)
            continue
        if target.exists():
            hints.append(item)
    return hints


def build_research_context(
    repo_root: str | Path,
    family: str | None = None,
    ledger_path: str | Path | None = None,
    process_memory_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a compact deterministic context pack using local files only."""
    root = Path(repo_root).resolve()
    ledger_target = _resolve(root, ledger_path, DEFAULT_LEDGER)
    process_target = _resolve(root, process_memory_path, DEFAULT_PROCESS_MEMORY)
    ledger_records = load_records(ledger_target)

    if family is not None and family not in FAMILIES:
        raise ValueError(f"family must be one of {sorted(FAMILIES)}")
    selected_family = family or _select_family(ledger_records)
    selected_status = compact_status(ledger_records, family=selected_family)

    runtime_memory = load_process_records(process_target)
    historical_target = root / HISTORICAL_PROCESS_MEMORY
    historical_memory = load_process_records(historical_target) if historical_target.exists() else []
    combined_memory = combine_process_records(historical_memory, runtime_memory)
    memory = process_memory_summary(combined_memory, family=selected_family)

    all_status = compact_status(ledger_records)
    parameter_only = all_status["change_class_counts"].get("PARAMETER_ONLY", 0)
    rejected = all_status["stage_counts"].get("REJECTED", 0)
    blocked = all_status["stage_counts"].get("BLOCKED", 0)
    head = _read_head(root)
    semantic = _semantic_status(root, selected_family, head)

    return {
        "schema_version": 1,
        "head": head,
        "family": selected_family,
        "network_io": False,
        "quota_policy": {
            "resume_source": "compact_context_only",
            "full_history_scan": False,
            "sealed_775_scan": False,
            "raw_log_scan": False,
            "model_roundtrips": "decision_only",
        },
        "ledger": selected_status,
        "process_memory": memory,
        "trial_accounting": {
            "ledger_trials": all_status["trial_count"],
            "unique_hypotheses": all_status["unique_hypotheses"],
            "parameter_only_records": parameter_only,
            "rejected_or_blocked_records": rejected + blocked,
            "semantic_candidates_filtered_before_llm": semantic["filtered_before_llm"],
        },
        "semantic_discovery": semantic,
        "memory_sources": {
            "historical_records": len(historical_memory),
            "runtime_records": len(runtime_memory),
        },
        "data_surface_hints": _data_surface_hints(root),
        "next_actions": _next_actions(selected_status),
    }


__all__ = [
    "DEFAULT_LEDGER",
    "DEFAULT_PROCESS_MEMORY",
    "HISTORICAL_PROCESS_MEMORY",
    "SEMANTIC_STATUS",
    "build_research_context",
    "read_repository_head",
]
