from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.catalog_profiler import profile_manifest, render_markdown
from hl_observer.datasets.github_release_bridge import (
    DEFAULT_RELEASE_ID,
    DEFAULT_REPOSITORY,
    DatasetBridgeError,
    ensure_metadata,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hl_observer.ops.dataset_catalog",
        description="Construit une carte lisible des données FULL/COLD sans télécharger les gros assets.",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--release-id", type=int, default=DEFAULT_RELEASE_ID)
    parser.add_argument("--force-metadata", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        _, _, metadata_dir = ensure_metadata(
            root,
            repository=args.repo,
            release_id=args.release_id,
            force=args.force_metadata,
        )
        manifest = metadata_dir / "FULL_UPLOADED_FILE_MANIFEST.jsonl.gz"
        profile = profile_manifest(manifest)
        report_dir = root / "runtime" / "reports" / "datasets"
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "CATALOGUE_COMPLET.json"
        md_path = report_dir / "CATALOGUE_COMPLET.md"
        json_path.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        md_path.write_text(render_markdown(profile), encoding="utf-8")
        print(f"CATALOGUE_OK fichiers={profile['total_files']} volume={profile['total_gib']} Gio")
        print(f"JSON={json_path}")
        print(f"MD={md_path}")
        return 0
    except (DatasetBridgeError, OSError, json.JSONDecodeError) as exc:
        print(f"CATALOGUE_NO_GO: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
