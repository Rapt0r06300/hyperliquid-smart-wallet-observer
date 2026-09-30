from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hl_observer.datasets.github_release_bridge import DatasetBridgeError

RELEASE_ID = 371149058
MAX_REPORT_BYTES = 5 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_small_text(path: Path) -> str:
    if not path.is_file():
        raise DatasetBridgeError(f"Rapport absent: {path}")
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise DatasetBridgeError(f"Rapport anormalement gros, export refusé: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _read_small_json(path: Path) -> Any:
    return json.loads(_read_small_text(path))


def _safe_suite_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)
    return safe or "dataset"


def export_result(
    project_root: Path,
    replay_root: Path,
    *,
    suite: str = "legacy-materialized",
) -> dict[str, object]:
    project_root = project_root.resolve()
    replay_root = replay_root.resolve()
    campaign_dir = replay_root / "runtime" / "reports" / "economic_campaigns"
    campaign_md = campaign_dir / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md"
    scoreboard_json = replay_root / "runtime" / "reports" / "economic_family_scoreboards.json"

    campaign_text = _read_small_text(campaign_md)
    scoreboards = _read_small_json(scoreboard_json)
    family_reports: dict[str, object] = {}
    for family in ("copy_vault", "lead_lag", "cross_venue_dislocation_v2"):
        path = campaign_dir / f"{family}.json"
        if path.is_file() and path.stat().st_size <= MAX_REPORT_BYTES:
            family_reports[family] = _read_small_json(path)

    destination = project_root / "docs" / "research" / "datasets"
    destination.mkdir(parents=True, exist_ok=True)
    safe_suite = _safe_suite_name(suite)
    suite_md_path = destination / f"DERNIER_REPLAY_180GO_{safe_suite}.md"
    suite_json_path = destination / f"DERNIER_REPLAY_180GO_{safe_suite}.json"
    canonical_md_path = destination / "DERNIER_REPLAY_DATASETS.md"
    canonical_json_path = destination / "DERNIER_REPLAY_DATASETS.json"
    legacy_md_path = destination / "DERNIER_REPLAY_176GO.md"
    legacy_json_path = destination / "DERNIER_REPLAY_176GO.json"
    generated = datetime.now(timezone.utc).isoformat()

    header = (
        "# Dernier replay des données FULL/COLD\n\n"
        f"- Release source : **{RELEASE_ID}**\n"
        f"- Suite source : **{suite}**\n"
        f"- Workspace : `{replay_root}`\n"
        f"- Généré UTC : `{generated}`\n"
        f"- SHA-256 rapport campagne : `{_sha256(campaign_md)}`\n"
        f"- SHA-256 scoreboard : `{_sha256(scoreboard_json)}`\n"
        "- Mode : **PAPER / READ-ONLY**\n"
        "- Exécution réelle : **NON**\n\n"
        "---\n\n"
    )
    markdown = header + campaign_text
    for path in (suite_md_path, canonical_md_path, legacy_md_path):
        path.write_text(markdown, encoding="utf-8")

    payload = {
        "schema": "hypersmart.dataset_replay_export.v2",
        "generated_at_utc": generated,
        "source_release_id": RELEASE_ID,
        "source_suite": suite,
        "replay_root": str(replay_root),
        "paper_read_only": True,
        "real_execution": False,
        "campaign_report_sha256": _sha256(campaign_md),
        "scoreboard_sha256": _sha256(scoreboard_json),
        "scoreboards": scoreboards,
        "family_campaigns": family_reports,
    }
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    for path in (suite_json_path, canonical_json_path, legacy_json_path):
        path.write_text(serialized, encoding="utf-8")

    return {
        "markdown": str(suite_md_path),
        "json": str(suite_json_path),
        "canonical_markdown": str(canonical_md_path),
        "canonical_json": str(canonical_json_path),
        "legacy_markdown": str(legacy_md_path),
        "legacy_json": str(legacy_json_path),
        "suite": suite,
        "families": sorted(family_reports),
        "status": "OK",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copie seulement le petit verdict final du replay vers docs/research."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--replay-root", required=True)
    parser.add_argument("--suite", default="legacy-materialized")
    args = parser.parse_args(argv)
    try:
        result = export_result(
            Path(args.root),
            Path(args.replay_root),
            suite=args.suite,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (DatasetBridgeError, OSError, json.JSONDecodeError) as exc:
        print(f"EXPORT_REPLAY_NO_GO: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
