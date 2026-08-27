from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Iterable

LOGGER = logging.getLogger(__name__)

DATASET_PROVENANCE = Path("runtime") / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
FAMILY_SOURCE_MANIFEST = Path("runtime") / "reports" / "datasets" / "FAMILY_SOURCES.json"

COPY_EXACT_NAMES = {
    "vault_fills.jsonl",
    "vault_fills_live.jsonl",
    "vault_ledger.jsonl",
    "vault_episodes.jsonl",
    "vault_snapshots.jsonl",
    "copy_vault_l2_tape.jsonl",
}
CROSS_EXACT_NAMES = {"carnet_venues.jsonl"}
REPLAY_EXACT_NAMES = {"candidates.jsonl", "marks.jsonl"}


def is_dataset_workspace(root: str | Path) -> bool:
    return (Path(root).resolve() / DATASET_PROVENANCE).is_file()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _is_generated_dataset_report(root: Path, path: Path) -> bool:
    reports = (root / "runtime" / "reports" / "datasets").resolve()
    try:
        path.resolve().relative_to(reports)
        return True
    except ValueError:
        return False


def _iter_real_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _is_generated_dataset_report(root, path):
            continue
        yield path


def _is_bbo_source(path: Path) -> bool:
    name = path.name.casefold()
    if name in {"bbo_tape.jsonl", "bbo_tape.jsonl.prev"}:
        return True
    if not name.endswith(".jsonl.gz"):
        return False
    parents = {part.casefold() for part in path.parts}
    return bool({"bbo_shards", "bbo_shards_archive"} & parents)


def _is_market_tick_source(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    return "market_ticks" in parts


def _is_log_source(path: Path) -> bool:
    lowered = [part.casefold() for part in path.parts]
    for index, part in enumerate(lowered[:-1]):
        if part != "logs":
            continue
        tail = lowered[index + 1 :]
        if "logs a envoyer" in tail or "logs à envoyer" in tail:
            return True
    return False


def _is_sqlite_source(path: Path) -> bool:
    name = path.name.casefold()
    return ".sqlite3" in name or name.endswith((".db", ".db-wal", ".db-shm"))


def _is_research_lab_source(path: Path) -> bool:
    parts = [part.casefold() for part in path.parts]
    for index, part in enumerate(parts[:-1]):
        if part == "research_lab":
            return True
        if part == "research-lab":
            return True
        if part == "runtime" and index + 1 < len(parts) and parts[index + 1] in {
            "research_lab",
            "research-lab",
        }:
            return True
    return False


def _entry(root: Path, path: Path) -> dict[str, object]:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {"path": _relative(root, path), "bytes": int(size)}


def discover_family_sources(root: str | Path) -> dict[str, list[Path]]:
    resolved = Path(root).resolve()
    groups: dict[str, list[Path]] = {
        "copy_vault": [],
        "lead_lag": [],
        "cross_venue": [],
        "market_ticks": [],
        "replay": [],
        "logs": [],
        "sqlite": [],
        "research_lab": [],
    }
    for path in _iter_real_files(resolved):
        name = path.name.casefold()
        if name in COPY_EXACT_NAMES:
            groups["copy_vault"].append(path)
        if _is_bbo_source(path):
            groups["lead_lag"].append(path)
        if name in CROSS_EXACT_NAMES:
            groups["cross_venue"].append(path)
        if _is_market_tick_source(path):
            groups["market_ticks"].append(path)
        if name in REPLAY_EXACT_NAMES:
            groups["replay"].append(path)
        if _is_log_source(path):
            groups["logs"].append(path)
        if _is_sqlite_source(path):
            groups["sqlite"].append(path)
        if _is_research_lab_source(path):
            groups["research_lab"].append(path)
    for key, values in groups.items():
        groups[key] = sorted(set(values), key=lambda item: item.as_posix().casefold())
    return groups


def write_family_source_manifest(root: str | Path) -> Path:
    resolved = Path(root).resolve()
    groups = discover_family_sources(resolved)
    payload: dict[str, object] = {
        "schema": "hypersmart.dataset_family_sources.v2",
        "dataset_workspace": is_dataset_workspace(resolved),
        "root": str(resolved),
        "groups": {},
    }
    rendered: dict[str, object] = {}
    for key, paths in groups.items():
        rows = [_entry(resolved, path) for path in paths]
        rendered[key] = {
            "file_count": len(rows),
            "bytes": sum(int(row["bytes"]) for row in rows),
            "files": rows,
        }
    payload["groups"] = rendered
    output = resolved / FAMILY_SOURCE_MANIFEST
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def load_family_source_paths(root: str | Path, family: str) -> list[Path]:
    resolved = Path(root).resolve()
    dataset_workspace = is_dataset_workspace(resolved)
    manifest = resolved / FAMILY_SOURCE_MANIFEST
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            groups = payload.get("groups", {}) if isinstance(payload, dict) else {}
            group = groups.get(family, {}) if isinstance(groups, dict) else {}
            files = group.get("files", []) if isinstance(group, dict) else []
            result: list[Path] = []
            stale_live_manifest = False
            manifest_mtime_ns = manifest.stat().st_mtime_ns
            watched_directories: set[Path] = set()
            for item in files:
                if not isinstance(item, dict):
                    continue
                relative = str(item.get("path") or "")
                if not relative:
                    continue
                path = (resolved / relative).resolve()
                try:
                    path.relative_to(resolved)
                except ValueError:
                    continue
                watched_directories.add(path.parent)
                if path.is_file():
                    result.append(path)
                    expected_bytes = item.get("bytes")
                    if (
                        not dataset_workspace
                        and isinstance(expected_bytes, int)
                        and path.stat().st_size != expected_bytes
                    ):
                        stale_live_manifest = True
                elif not dataset_workspace:
                    stale_live_manifest = True

            if not dataset_workspace:
                watched_directories.update(
                    {
                        resolved / "runtime" / "data",
                        resolved / "runtime" / "replay",
                        resolved / "runtime" / "research_lab",
                        resolved / "logs",
                    }
                )
                stale_live_manifest = stale_live_manifest or any(
                    directory.is_dir() and directory.stat().st_mtime_ns > manifest_mtime_ns
                    for directory in watched_directories
                )

            if result and not stale_live_manifest:
                return sorted(set(result), key=lambda item: item.as_posix().casefold())
            if stale_live_manifest:
                LOGGER.info(
                    "Manifeste live obsolète pour %s; redécouverte des sources présentes.",
                    family,
                )
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            LOGGER.warning(
                "Manifeste de sources illisible pour %s (%s); redécouverte du workspace.",
                family,
                type(exc).__name__,
            )
    return discover_family_sources(resolved).get(family, [])


def source_manifest_summary(root: str | Path) -> dict[str, object]:
    resolved = Path(root).resolve()
    groups = discover_family_sources(resolved)
    result: dict[str, object] = {}
    for key, paths in groups.items():
        total = 0
        for path in paths:
            try:
                total += path.stat().st_size
            except OSError:
                continue
        result[key] = {"file_count": len(paths), "bytes": total}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventorie les sources économiques, SQLite et Research Lab d'un workspace FULL/COLD."
    )
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"DATASET_SOURCES_NO_GO: dossier absent: {root}")
        return 2
    manifest = write_family_source_manifest(root)
    print(
        json.dumps(
            {
                "manifest": str(manifest),
                "dataset_workspace": is_dataset_workspace(root),
                "summary": source_manifest_summary(root),
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
