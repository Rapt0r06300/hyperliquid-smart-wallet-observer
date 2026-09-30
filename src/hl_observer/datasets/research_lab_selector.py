from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.research_lab_stream import REPORT_JSON

SELECTION_DIR = Path("runtime") / "reports" / "datasets" / "research_selections"
CURRENT_SELECTION = SELECTION_DIR / "CURRENT_RESEARCH_SELECTION.json"


def load_research_profile(root: str | Path) -> dict[str, Any]:
    path = Path(root).resolve() / REPORT_JSON
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            "Profil Research Lab absent. Lance d'abord dataset_research_inventory."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Profil Research Lab illisible: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Profil Research Lab invalide.")
    return payload


def _counter_presence(raw: object, key: str | None) -> tuple[bool, bool]:
    """Return (accepted, uncertain). Empty/missing counters cannot prove absence."""

    if not key:
        return True, False
    if not isinstance(raw, Mapping) or not raw:
        return True, True
    normalized = key.casefold()
    for candidate, count in raw.items():
        if str(candidate).casefold() == normalized and int(count or 0) > 0:
            return True, False
    return False, False


def _metric_presence(raw: object, metric: str | None) -> tuple[bool, bool]:
    if not metric:
        return True, False
    if not isinstance(raw, Mapping) or not raw:
        return True, True
    for candidate, state in raw.items():
        if str(candidate).casefold() != metric.casefold():
            continue
        if isinstance(state, Mapping) and int(state.get("count") or 0) > 0:
            return True, False
        return False, False
    return False, False


def _time_overlap(
    item: Mapping[str, Any],
    *,
    start_ms: int | None,
    end_ms: int | None,
    include_unknown_time: bool,
) -> tuple[bool, bool]:
    if start_ms is None and end_ms is None:
        return True, False
    first = item.get("timestamp_min_ms")
    last = item.get("timestamp_max_ms")
    if first is None or last is None:
        return include_unknown_time, include_unknown_time
    first_i = int(first)
    last_i = int(last)
    if start_ms is not None and last_i < int(start_ms):
        return False, False
    if end_ms is not None and first_i > int(end_ms):
        return False, False
    return True, False


def select_research_files(
    profile: Mapping[str, Any],
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    family: str | None = None,
    coin: str | None = None,
    metric: str | None = None,
    require_complete: bool = False,
    include_unknown_time: bool = True,
) -> dict[str, Any]:
    if start_ms is not None and end_ms is not None and int(start_ms) > int(end_ms):
        raise ValueError("start_ms doit être inférieur ou égal à end_ms")
    raw_files = profile.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    selected: list[dict[str, Any]] = []
    rejected_counts = {
        "incomplete": 0,
        "time": 0,
        "family": 0,
        "coin": 0,
        "metric": 0,
    }
    uncertain_count = 0
    for raw in files:
        if not isinstance(raw, Mapping):
            continue
        if require_complete and raw.get("complete") is not True:
            rejected_counts["incomplete"] += 1
            continue
        time_ok, time_uncertain = _time_overlap(
            raw,
            start_ms=start_ms,
            end_ms=end_ms,
            include_unknown_time=include_unknown_time,
        )
        if not time_ok:
            rejected_counts["time"] += 1
            continue
        family_ok, family_uncertain = _counter_presence(raw.get("family_counts"), family)
        if not family_ok:
            rejected_counts["family"] += 1
            continue
        coin_ok, coin_uncertain = _counter_presence(raw.get("coin_counts"), coin)
        if not coin_ok:
            rejected_counts["coin"] += 1
            continue
        metric_ok, metric_uncertain = _metric_presence(raw.get("metrics"), metric)
        if not metric_ok:
            rejected_counts["metric"] += 1
            continue
        uncertain = bool(time_uncertain or family_uncertain or coin_uncertain or metric_uncertain)
        if uncertain:
            uncertain_count += 1
        selected.append(
            {
                "relative_path": raw.get("relative_path"),
                "source_size": int(raw.get("source_size") or 0),
                "source_gib": round(int(raw.get("source_size") or 0) / (1024**3), 4),
                "timestamp_min_ms": raw.get("timestamp_min_ms"),
                "timestamp_max_ms": raw.get("timestamp_max_ms"),
                "complete": raw.get("complete") is True,
                "checkpoint": raw.get("checkpoint"),
                "selection_uncertain": uncertain,
            }
        )

    criteria = {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "family": family,
        "coin": coin.upper() if coin else None,
        "metric": metric,
        "require_complete": bool(require_complete),
        "include_unknown_time": bool(include_unknown_time),
    }
    material = {
        "criteria": criteria,
        "files": [item["relative_path"] for item in selected],
    }
    digest = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "hypersmart.research_lab_selection.v1",
        "selection_digest": digest,
        "criteria": criteria,
        "profile_schema": profile.get("schema"),
        "profile_root": profile.get("root"),
        "candidate_file_count": len(files),
        "selected_file_count": len(selected),
        "selected_source_bytes": sum(int(item["source_size"]) for item in selected),
        "selected_source_gib": round(
            sum(int(item["source_size"]) for item in selected) / (1024**3), 4
        ),
        "uncertain_selected_file_count": uncertain_count,
        "rejected_counts": rejected_counts,
        "files": selected,
        "raw_events_copied": False,
    }


def write_research_selection(
    root: str | Path,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    family: str | None = None,
    coin: str | None = None,
    metric: str | None = None,
    require_complete: bool = False,
    include_unknown_time: bool = True,
) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    profile = load_research_profile(resolved)
    selection = select_research_files(
        profile,
        start_ms=start_ms,
        end_ms=end_ms,
        family=family,
        coin=coin,
        metric=metric,
        require_complete=require_complete,
        include_unknown_time=include_unknown_time,
    )
    directory = resolved / SELECTION_DIR
    directory.mkdir(parents=True, exist_ok=True)
    digest = str(selection["selection_digest"])
    json_path = directory / f"selection_{digest[:16]}.json"
    current_path = resolved / CURRENT_SELECTION
    text = json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path.write_text(text, encoding="utf-8")
    current_path.write_text(text, encoding="utf-8")
    return json_path, current_path, selection


__all__ = [
    "CURRENT_SELECTION",
    "SELECTION_DIR",
    "load_research_profile",
    "select_research_files",
    "write_research_selection",
]
