from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.research_lab_stream import write_research_stream_profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Profile en streaming les gros JSONL du Research Lab FULL/COLD. "
            "Le scan est local, read-only, reprenable et sans chargement complet en RAM."
        )
    )
    parser.add_argument("--root", required=True, help="Workspace FULL/COLD reconstruit.")
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Nombre maximal de fichiers à profiler. 0 = tous.",
    )
    parser.add_argument(
        "--max-gib-per-file",
        type=float,
        default=0.0,
        help="Volume maximal parcouru par fichier pour ce run. 0 = jusqu'à EOF.",
    )
    parser.add_argument(
        "--max-lines-per-file",
        type=int,
        default=0,
        help="Nombre maximal de lignes par fichier. 0 = illimité.",
    )
    parser.add_argument(
        "--sample-every",
        type=int,
        default=100_000,
        help="Conserve un échantillon de métadonnées toutes les N lignes. 0 = aucun.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=5.0,
        help="Fréquence de progression pendant les gros scans.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore les checkpoints existants et recommence les fichiers non compressés.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"RESEARCH_INVENTORY_NO_GO: workspace absent: {root}")
        return 2
    max_bytes = max(0, int(float(args.max_gib_per_file) * 1024**3))
    try:
        json_path, md_path, profile = write_research_stream_profile(
            root,
            resume=not bool(args.no_resume),
            max_files=max(0, int(args.max_files)),
            max_bytes_per_file=max_bytes,
            max_lines_per_file=max(0, int(args.max_lines_per_file)),
            sample_every=max(0, int(args.sample_every)),
            heartbeat_seconds=max(0.2, float(args.heartbeat_seconds)),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RESEARCH_INVENTORY_NO_GO: {type(exc).__name__}: {exc}")
        return 2

    payload = {
        "file_count": profile.get("file_count", 0),
        "complete_file_count": profile.get("complete_file_count", 0),
        "partial_file_count": profile.get("partial_file_count", 0),
        "source_gib": profile.get("source_gib", 0),
        "scanned_gib": profile.get("scanned_gib", 0),
        "lines": profile.get("lines", 0),
        "invalid_json": profile.get("invalid_json", 0),
        "report_json": str(json_path),
        "report_markdown": str(md_path),
        "read_only": True,
        "resume_enabled": not bool(args.no_resume),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
