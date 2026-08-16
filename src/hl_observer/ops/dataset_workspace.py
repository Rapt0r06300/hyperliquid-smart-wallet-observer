from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.github_release_bridge import DatasetBridgeError
from hl_observer.datasets.replay_workspace import prepare_replay_workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hl_observer.ops.dataset_workspace",
        description="Prépare les données FULL/COLD pour les moteurs de replay existants.",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--materialized-root", default=None)
    args = parser.parse_args(argv)
    project_root = Path(args.root).resolve()
    materialized_root = (
        Path(args.materialized_root).resolve() if args.materialized_root else None
    )
    try:
        result = prepare_replay_workspace(
            project_root,
            materialized_root=materialized_root,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (DatasetBridgeError, OSError) as exc:
        print(f"ESPACE_REPLAY_NO_GO: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
