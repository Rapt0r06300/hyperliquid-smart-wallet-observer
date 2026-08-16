from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.research_lab_selector import write_research_selection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sélectionne dans le profil Research Lab les fichiers pertinents pour une expérience, "
            "sans rescanner ni recopier les gros JSONL."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--start-ms", type=int, default=None)
    parser.add_argument("--end-ms", type=int, default=None)
    parser.add_argument("--family", default=None)
    parser.add_argument("--coin", default=None)
    parser.add_argument("--metric", default=None)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument(
        "--exclude-unknown-time",
        action="store_true",
        help=(
            "Exclut les fichiers dont le profil n'a pas de bornes temporelles. Par défaut ils sont "
            "conservés avec selection_uncertain=true pour éviter une omission silencieuse."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"RESEARCH_SELECT_NO_GO: workspace absent: {root}")
        return 2
    try:
        path, current, selection = write_research_selection(
            root,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            family=args.family,
            coin=args.coin,
            metric=args.metric,
            require_complete=bool(args.require_complete),
            include_unknown_time=not bool(args.exclude_unknown_time),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"RESEARCH_SELECT_NO_GO: {type(exc).__name__}: {exc}")
        return 2
    print(
        json.dumps(
            {
                "selection_digest": selection.get("selection_digest"),
                "candidate_file_count": selection.get("candidate_file_count", 0),
                "selected_file_count": selection.get("selected_file_count", 0),
                "selected_source_gib": selection.get("selected_source_gib", 0),
                "uncertain_selected_file_count": selection.get("uncertain_selected_file_count", 0),
                "selection_path": str(path),
                "current_selection_path": str(current),
                "criteria": selection.get("criteria", {}),
                "raw_events_copied": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
