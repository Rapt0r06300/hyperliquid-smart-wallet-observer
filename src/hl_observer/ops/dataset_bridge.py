from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.github_release_bridge import (
    DEFAULT_RELEASE_ID,
    DEFAULT_REPOSITORY,
    DatasetBridgeError,
    assets_for_records,
    build_status,
    download_needed_assets,
    ensure_metadata,
    iter_manifest_records,
    materialize_records,
    select_records,
)

FAMILY_PATTERNS = {
    "copy-vault": (
        "copy_vault",
        "copy-vault",
        "vault",
        "userfills",
        "user_fills",
        "leader",
    ),
    "lead-lag": (
        "lead_lag",
        "lead-lag",
        "allmids",
        "bbo",
        "trades",
        "microprice",
        "orderflow",
    ),
    "cross-venue": (
        "cross_venue",
        "cross-venue",
        "carnet_venues",
        "venue",
        "binance",
        "dydx",
        "dislocation",
    ),
}

PRESET_PATTERNS = {
    "economic-core": (
        "runtime/data/vault_fills.jsonl",
        "runtime/data/vault_fills_live.jsonl",
        "runtime/data/vault_ledger.jsonl",
        "runtime/data/vault_episodes.jsonl",
        "runtime/data/vault_snapshots.jsonl",
        "runtime/data/copy_vault_l2_tape.jsonl",
        "runtime/data/carnet_venues.jsonl",
        "runtime/data/bbo_tape.jsonl",
        "runtime/data/bbo_tape.jsonl.prev",
        "runtime/data/bbo_shards/",
        "runtime/data/bbo_shards_archive/",
        "runtime/data/lead_lag_config_gele.json",
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hl_observer.ops.dataset_bridge",
        description=(
            "Pont sûr entre la Release privée hypersmart-datasets et les replays locaux. "
            "Aucun ordre réel, aucune écriture sur un exchange."
        ),
    )
    parser.add_argument("action", choices=("status", "catalog", "find", "prepare"))
    parser.add_argument("--root", default=".", help="Racine locale du projet HyperSmart.")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--release-id", type=int, default=DEFAULT_RELEASE_ID)
    parser.add_argument("--contains", action="append", default=[])
    parser.add_argument("--suffix", action="append", default=[])
    parser.add_argument("--family", choices=tuple(FAMILY_PATTERNS), default=None)
    parser.add_argument("--preset", choices=tuple(PRESET_PATTERNS), default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Autorise le téléchargement des gros assets sélectionnés.",
    )
    parser.add_argument(
        "--max-download-gib",
        type=float,
        default=20.0,
        help="Plafond de téléchargement. 0 = illimité. Défaut: 20 Gio.",
    )
    return parser


def _patterns(args: argparse.Namespace) -> list[str]:
    patterns = list(args.contains)
    if args.family:
        patterns.extend(FAMILY_PATTERNS[args.family])
    if args.preset:
        patterns.extend(PRESET_PATTERNS[args.preset])
    return patterns


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def _load_selected(args: argparse.Namespace):
    root = Path(args.root).resolve()
    release, assets, metadata_dir = ensure_metadata(
        root,
        repository=args.repo,
        release_id=args.release_id,
        force=args.force,
    )
    manifest = metadata_dir / "FULL_UPLOADED_FILE_MANIFEST.jsonl.gz"
    selected = select_records(
        iter_manifest_records(manifest),
        contains=_patterns(args),
        suffixes=args.suffix,
        limit=args.limit,
    )
    return root, release, assets, metadata_dir, selected


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.action == "status":
            _print_json(
                build_status(root, repository=args.repo, release_id=args.release_id)
            )
            return 0

        root, release, assets, metadata_dir, selected = _load_selected(args)
        if args.action == "catalog":
            summary_path = metadata_dir / "FULL_SNAPSHOT_SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            _print_json(
                {
                    "release_name": release.get("name"),
                    "published_at": release.get("published_at"),
                    "asset_count": len(assets),
                    "metadata_dir": str(metadata_dir),
                    "snapshot": summary,
                }
            )
            return 0

        asset_names = assets_for_records(selected)
        total_asset_bytes = sum(assets[name].size for name in asset_names if name in assets)
        preview = {
            "fichiers_selectionnes": len(selected),
            "assets_necessaires": len(asset_names),
            "octets_a_telecharger": total_asset_bytes,
            "gib_a_telecharger": round(total_asset_bytes / (1024**3), 3),
            "famille": args.family,
            "preset": args.preset,
            "premiers_fichiers": [item.relative_path for item in selected[:50]],
        }

        if args.action == "find":
            _print_json(preview)
            return 0

        if not selected:
            raise DatasetBridgeError(
                "Aucun fichier ne correspond aux critères. Rien n'est téléchargé."
            )
        if not args.download:
            _print_json(preview)
            print(
                "\nMode aperçu seulement. Ajoute --download pour récupérer et reconstruire ces fichiers."
            )
            return 0

        max_bytes = int(args.max_download_gib * 1024**3)
        if max_bytes > 0 and total_asset_bytes > max_bytes:
            raise DatasetBridgeError(
                f"Le plan demande {total_asset_bytes / (1024**3):.2f} Gio, "
                f"au-dessus du plafond de {args.max_download_gib:.2f} Gio. "
                "Relève --max-download-gib ou mets 0 si tu veux vraiment tout prendre."
            )

        downloaded = download_needed_assets(
            root,
            assets,
            asset_names,
            repository=args.repo,
            force=args.force,
        )
        output_root = root / "data" / "hypersmart_datasets" / "materialized"
        created = materialize_records(selected, downloaded, output_root)
        report = {
            **preview,
            "fichiers_reconstruits": len(created),
            "dossier_reconstruit": str(output_root),
            "etat": "OK",
        }
        report_dir = root / "runtime" / "reports" / "datasets"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "DERNIERE_PREPARATION_DATASET.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _print_json(report)
        print(f"\nRapport: {report_path}")
        return 0
    except (DatasetBridgeError, OSError, json.JSONDecodeError) as exc:
        print(f"DATASET_BRIDGE_NO_GO: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
