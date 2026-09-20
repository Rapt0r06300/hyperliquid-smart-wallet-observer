from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.continuous_vault import (
    load_continuous_pointer,
    prepare_continuous_suite,
    resolve_continuous_workspace,
)
from hl_observer.datasets.github_release_bridge import (
    DEFAULT_REPOSITORY,
    DatasetBridgeError,
)
from hl_observer.datasets.archive_library import suite_names


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hl_observer.ops.continuous_vault",
        description=(
            "Pont read-only entre le Continuous Data Vault GitHub privé "
            "et les replays/backtests Alina."
        ),
    )
    parser.add_argument(
        "action",
        choices=("status", "prepare", "locate"),
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--ref", default="main")
    parser.add_argument("--suite", choices=suite_names(), default=None)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--present-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-download-gib", type=float, default=20.0)
    parser.add_argument("--disk-reserve-gib", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()

    try:
        if args.action == "status":
            pointer = load_continuous_pointer(
                repository=args.repo,
                ref=args.ref,
            )
            print(
                json.dumps(
                    {
                        "repository": args.repo,
                        "ref": args.ref,
                        "latest_snapshot_id": pointer.get("latest_snapshot_id"),
                        "latest_release_id": pointer.get("latest_release_id"),
                        "latest_release_tag": pointer.get("latest_release_tag"),
                        "snapshot_summary": pointer.get("snapshot_summary"),
                        "paper_only": True,
                        "real_execution": False,
                    },
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0

        if not args.suite:
            raise DatasetBridgeError(
                f"{args.action} exige --suite."
            )

        if args.action == "locate":
            print(resolve_continuous_workspace(root, args.suite))
            return 0

        result = prepare_continuous_suite(
            root,
            suite=args.suite,
            repository=args.repo,
            ref=args.ref,
            present_only=args.present_only,
            download=args.download,
            force=args.force,
            max_download_gib=args.max_download_gib,
            disk_reserve_gib=args.disk_reserve_gib,
        )
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )
        if not args.download:
            print(
                "\nMode aperçu seulement. Ajoute --download pour reconstruire la suite."
            )
        return 0

    except (DatasetBridgeError, OSError, json.JSONDecodeError) as exc:
        print(f"CONTINUOUS_VAULT_NO_GO: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
