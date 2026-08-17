from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from hl_observer.datasets.archive_library import (
    COPY_VAULT_PATTERNS,
    CROSS_VENUE_PATTERNS,
    ECONOMIC_CORE_PATTERNS,
    LEAD_LAG_PATTERNS,
    build_all_suite_plans,
    build_selection_plan,
    render_library_markdown,
    resolve_current_workspace,
    select_suite_records,
    suite_names,
    suite_workspace_for_digest,
    write_current_workspace,
)
from hl_observer.datasets.github_release_bridge import (
    DEFAULT_RELEASE_ID,
    DEFAULT_REPOSITORY,
    DatasetBridgeError,
    assets_for_records,
    iter_manifest_records,
    materialize_records,
    select_records,
)
from hl_observer.datasets.progress_downloader import (
    cache_transfer_plan,
    download_needed_assets_with_progress,
)
from hl_observer.datasets.release_gateway import (
    build_release_status,
    ensure_release_metadata,
)

# Compatibilité avec les commandes/tests historiques.
FAMILY_PATTERNS = {
    "copy-vault": COPY_VAULT_PATTERNS,
    "lead-lag": LEAD_LAG_PATTERNS,
    "cross-venue": CROSS_VENUE_PATTERNS,
}

PRESET_PATTERNS = {
    "economic-core": ECONOMIC_CORE_PATTERNS,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hl_observer.ops.dataset_bridge",
        description=(
            "Pont sûr entre la Release privée hypersmart-datasets et les replays locaux. "
            "Aucun ordre réel, aucune écriture sur un exchange."
        ),
    )
    parser.add_argument(
        "action",
        choices=("status", "catalog", "find", "plan-all", "locate", "prepare"),
    )
    parser.add_argument("--root", default=".", help="Racine locale du projet Alina SmartFlow.")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--release-id", type=int, default=DEFAULT_RELEASE_ID)
    parser.add_argument("--contains", action="append", default=[])
    parser.add_argument("--suffix", action="append", default=[])
    parser.add_argument("--family", choices=tuple(FAMILY_PATTERNS), default=None)
    parser.add_argument("--preset", choices=tuple(PRESET_PATTERNS), default=None)
    parser.add_argument("--suite", choices=suite_names(), default=None)
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
        help="Plafond du trafic réseau restant de ce cycle. 0 = illimité. Défaut: 20 Gio.",
    )
    parser.add_argument(
        "--disk-reserve-gib",
        type=float,
        default=5.0,
        help="Réserve disque minimale conservée après cache+reconstruction estimés. Défaut: 5 Gio.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=1.0,
        help="Fréquence d'affichage pendant un téléchargement. Défaut: 1 seconde.",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_download_gib < 0:
        raise DatasetBridgeError("--max-download-gib ne peut pas être négatif.")
    if args.disk_reserve_gib < 0:
        raise DatasetBridgeError("--disk-reserve-gib ne peut pas être négatif.")
    if args.suite:
        mixed = bool(
            args.contains
            or args.suffix
            or args.family
            or args.preset
            or args.limit is not None
        )
        if mixed:
            raise DatasetBridgeError(
                "--suite décrit une sélection reproductible complète. "
                "Ne la mélange pas avec --contains/--suffix/--family/--preset/--limit."
            )
    if args.action == "locate" and not args.suite:
        raise DatasetBridgeError("locate exige --suite.")
    if args.action == "plan-all" and any(
        (args.contains, args.suffix, args.family, args.preset, args.suite)
    ):
        raise DatasetBridgeError("plan-all calcule toutes les suites et n'accepte aucun filtre.")


def _patterns(args: argparse.Namespace) -> list[str]:
    patterns = list(args.contains)
    if args.family:
        patterns.extend(FAMILY_PATTERNS[args.family])
    if args.preset:
        patterns.extend(PRESET_PATTERNS[args.preset])
    return patterns


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def _load_context(args: argparse.Namespace):
    root = Path(args.root).resolve()
    release, assets, metadata_dir = ensure_release_metadata(
        root,
        repository=args.repo,
        release_id=args.release_id,
        force=args.force,
    )
    manifest = metadata_dir / "FULL_UPLOADED_FILE_MANIFEST.jsonl.gz"
    return root, release, assets, metadata_dir, manifest


def snapshot_fingerprint(
    manifest: Path,
    release: dict[str, object],
    assets,
    *,
    repository: str,
    release_id: int,
) -> str:
    """Bind a run to the physical manifest and immutable asset descriptors."""

    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "repository": repository,
                "release_id": int(release_id),
                "release_name": release.get("name"),
                "tag_name": release.get("tag_name"),
                "published_at": release.get("published_at"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    if not manifest.is_file():
        raise DatasetBridgeError(f"Manifeste FULL/COLD absent: {manifest}")
    with manifest.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    for name in sorted(assets):
        asset = assets[name]
        digest.update(
            f"\n{name}\0{int(asset.size)}\0{str(asset.sha256 or '')}\0{int(asset.asset_id)}".encode(
                "utf-8"
            )
        )
    return digest.hexdigest()


def _legacy_preview(
    selected,
    assets,
    *,
    family: str | None,
    preset: str | None,
) -> dict[str, object]:
    asset_names = assets_for_records(selected)
    missing_assets = [name for name in asset_names if name not in assets]
    if missing_assets:
        raise DatasetBridgeError(
            "Le manifeste cite des assets absents de la Release: "
            + ", ".join(missing_assets[:20])
        )
    total_asset_bytes = sum(assets[name].size for name in asset_names)
    raw_bytes = sum(item.size for item in selected)
    return {
        "fichiers_selectionnes": len(selected),
        "octets_bruts_selectionnes": raw_bytes,
        "gib_bruts_selectionnes": round(raw_bytes / (1024**3), 4),
        "assets_necessaires": len(asset_names),
        "octets_a_telecharger": total_asset_bytes,
        "gib_a_telecharger": round(total_asset_bytes / (1024**3), 3),
        "famille": family,
        "preset": preset,
        "premiers_fichiers": [item.relative_path for item in selected[:50]],
    }


def _write_library_reports(
    root: Path,
    release: dict[str, object],
    plans: dict[str, dict[str, object]],
    *,
    release_id: int,
) -> tuple[Path, Path]:
    report_dir = root / "runtime" / "reports" / "datasets"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "BIBLIOTHEQUE_180GO.json"
    md_path = report_dir / "BIBLIOTHEQUE_180GO.md"
    payload = {
        "schema": "hypersmart.dataset_library.v1",
        "release_id": release_id,
        "release_name": release.get("name"),
        "tag_name": release.get("tag_name"),
        "published_at": release.get("published_at"),
        "plans": plans,
        "paper_read_only": True,
        "real_execution": False,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        render_library_markdown(plans, release_id=release_id),
        encoding="utf-8",
    )
    return json_path, md_path


def _write_preparation_provenance(
    output_root: Path,
    *,
    release: dict[str, object],
    release_id: int,
    preview: dict[str, object],
) -> Path:
    report_dir = output_root / "runtime" / "reports" / "datasets"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "SELECTION_PROVENANCE.json"
    payload = {
        "schema": "hypersmart.dataset_selection_provenance.v2",
        "source_release_id": release_id,
        "source_release_name": release.get("name"),
        "source_tag_name": release.get("tag_name"),
        "paper_read_only": True,
        "real_execution": False,
        **preview,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _disk_guard(
    root: Path,
    *,
    network_remaining_bytes: int,
    raw_materialized_bytes: int,
    reserve_gib: float,
) -> dict[str, object]:
    free = int(shutil.disk_usage(root).free)
    reserve = int(float(reserve_gib) * 1024**3)
    worst_case_required = max(0, int(network_remaining_bytes)) + max(0, int(raw_materialized_bytes)) + reserve
    return {
        "free_bytes": free,
        "reserve_bytes": reserve,
        "network_remaining_bytes": max(0, int(network_remaining_bytes)),
        "raw_materialized_bytes_worst_case": max(0, int(raw_materialized_bytes)),
        "worst_case_required_bytes": worst_case_required,
        "ok": free >= worst_case_required,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        _validate_args(args)

        if args.action == "status":
            _print_json(
                build_release_status(root, repository=args.repo, release_id=args.release_id)
            )
            return 0

        if args.action == "locate":
            print(resolve_current_workspace(root, args.suite))
            return 0

        root, release, assets, metadata_dir, manifest = _load_context(args)
        snapshot_sha256 = snapshot_fingerprint(
            manifest,
            release,
            assets,
            repository=args.repo,
            release_id=args.release_id,
        )

        if args.action == "catalog":
            summary_path = metadata_dir / "FULL_SNAPSHOT_SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            _print_json(
                {
                    "release_name": release.get("name"),
                    "published_at": release.get("published_at"),
                    "asset_count": len(assets),
                    "assets_with_sha256": sum(1 for asset in assets.values() if asset.sha256),
                    "metadata_dir": str(metadata_dir),
                    "snapshot": summary,
                    "snapshot_fingerprint_sha256": snapshot_sha256,
                    "suites_disponibles": list(suite_names()),
                }
            )
            return 0

        if args.action == "plan-all":
            plans = build_all_suite_plans(
                iter_manifest_records(manifest),
                assets,
                project_root=root,
            )
            json_path, md_path = _write_library_reports(
                root,
                release,
                plans,
                release_id=args.release_id,
            )
            payload = {
                "release_id": args.release_id,
                "release_name": release.get("name"),
                "snapshot_fingerprint_sha256": snapshot_sha256,
                "plans": plans,
                "rapport_json": str(json_path),
                "rapport_markdown": str(md_path),
            }
            _print_json(payload)
            return 0

        records = iter_manifest_records(manifest)
        if args.suite:
            selected = select_suite_records(records, args.suite)
            preview = build_selection_plan(
                selected,
                assets,
                args.suite,
                project_root=root,
            )
            asset_names = tuple(preview["needed_assets"])
            missing_assets = list(preview["missing_assets"])
            output_root = suite_workspace_for_digest(
                root,
                args.suite,
                str(preview["selection_digest"]),
            )
        else:
            selected = select_records(
                records,
                contains=_patterns(args),
                suffixes=args.suffix,
                limit=args.limit,
            )
            preview = _legacy_preview(
                selected,
                assets,
                family=args.family,
                preset=args.preset,
            )
            asset_names = assets_for_records(selected)
            missing_assets = [name for name in asset_names if name not in assets]
            output_root = root / "data" / "hypersmart_datasets" / "materialized"

        if missing_assets:
            raise DatasetBridgeError(
                "Le manifeste cite des assets absents de la Release: "
                + ", ".join(missing_assets[:20])
            )

        transfer_plan = cache_transfer_plan(root, assets, asset_names, force=args.force)
        preview = {
            **preview,
            "snapshot_fingerprint_sha256": snapshot_sha256,
            "verified_cache_bytes": int(transfer_plan["verified_cache_bytes"]),
            "partial_cache_bytes": int(transfer_plan["partial_cache_bytes"]),
            "remaining_network_bytes": int(transfer_plan["remaining_network_bytes"]),
            "remaining_network_gib": round(int(transfer_plan["remaining_network_bytes"]) / (1024**3), 4),
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

        remaining_network_bytes = int(transfer_plan["remaining_network_bytes"])
        max_bytes = int(args.max_download_gib * 1024**3)
        if max_bytes > 0 and remaining_network_bytes > max_bytes:
            raise DatasetBridgeError(
                f"Le réseau restant demande {remaining_network_bytes / (1024**3):.2f} Gio, "
                f"au-dessus du plafond de {args.max_download_gib:.2f} Gio. "
                "Le cache déjà vérifié et les .part repris ne sont pas recomptés. "
                "Relève --max-download-gib ou mets 0 si tu veux réellement tout prendre."
            )

        raw_materialized_bytes = sum(int(item.size) for item in selected)
        disk = _disk_guard(
            root,
            network_remaining_bytes=remaining_network_bytes,
            raw_materialized_bytes=raw_materialized_bytes,
            reserve_gib=args.disk_reserve_gib,
        )
        preview["disk_guard"] = disk
        if disk["ok"] is not True:
            raise DatasetBridgeError(
                "Espace disque insuffisant pour le pire cas cache+reconstruction+réserve: "
                f"libre={int(disk['free_bytes']) / (1024**3):.2f} Gio, "
                f"requis={int(disk['worst_case_required_bytes']) / (1024**3):.2f} Gio."
            )

        downloaded = download_needed_assets_with_progress(
            root,
            assets,
            asset_names,
            repository=args.repo,
            force=args.force,
            heartbeat_seconds=max(0.2, float(args.heartbeat_seconds)),
        )
        print(
            f"[RECONSTRUCTION] {len(selected)} fichier(s) sélectionné(s) vers {output_root}",
            flush=True,
        )
        created = materialize_records(selected, downloaded, output_root)
        report = {
            **preview,
            "fichiers_reconstruits": len(created),
            "dossier_reconstruit": str(output_root),
            "source_repository": args.repo,
            "source_release_id": args.release_id,
            "source_release_name": release.get("name"),
            "snapshot_fingerprint_sha256": snapshot_sha256,
            "etat": "OK",
        }
        provenance_path = _write_preparation_provenance(
            output_root,
            release=release,
            release_id=args.release_id,
            preview=report,
        )
        if args.suite:
            pointer = write_current_workspace(
                root,
                args.suite,
                digest=str(preview["selection_digest"]),
                workspace=output_root,
                release_id=args.release_id,
            )
            report["pointeur_courant"] = str(pointer)
        report["provenance"] = str(provenance_path)

        report_dir = root / "runtime" / "reports" / "datasets"
        report_dir.mkdir(parents=True, exist_ok=True)
        suffix = args.suite or args.preset or args.family or "custom"
        safe_suffix = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in suffix)
        report_path = report_dir / f"DERNIERE_PREPARATION_{safe_suffix}.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        legacy_report = report_dir / "DERNIERE_PREPARATION_DATASET.json"
        legacy_report.write_text(
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
