from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hl_observer.analysis.v19_repo_matrix import V19_REPO_FUSION_ITEMS  # noqa: E402


PERMISSIVE_LICENSES = {
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "mit",
    "mpl-2.0",
}


@dataclass(frozen=True, slots=True)
class V24RepoIntake:
    repo: str
    url: str
    priority: str
    owner_repo: str
    license_spdx: str
    license_status: str
    portage_policy: str
    github_status: str
    default_branch: str | None
    observed_files: tuple[str, ...]
    target_modules: tuple[str, ...]
    target_tests: tuple[str, ...]
    ideas_to_port: tuple[str, ...]
    paper_transform: str
    real_action_boundary: str


def build_v24_intake(*, network_read: bool = False, max_files_per_repo: int = 18) -> list[V24RepoIntake]:
    rows: list[V24RepoIntake] = []
    for item in V19_REPO_FUSION_ITEMS:
        owner_repo = _owner_repo_from_url(item.url)
        metadata = _github_metadata(owner_repo, network_read=network_read)
        license_spdx = metadata.get("license_spdx", "UNKNOWN")
        license_status = metadata.get("license_status", "network_read_disabled" if not network_read else "unknown")
        default_branch = metadata.get("default_branch")
        observed_files = _github_tree_files(
            owner_repo,
            default_branch=default_branch,
            network_read=network_read,
            max_files=max_files_per_repo,
        )
        rows.append(
            V24RepoIntake(
                repo=item.name,
                url=item.url,
                priority=item.priority,
                owner_repo=owner_repo,
                license_spdx=license_spdx,
                license_status=license_status,
                portage_policy=_portage_policy(license_spdx, license_status),
                github_status=metadata.get("github_status", "not_checked"),
                default_branch=default_branch,
                observed_files=tuple(observed_files),
                target_modules=tuple(item.target_modules),
                target_tests=tuple(item.target_tests),
                ideas_to_port=tuple(item.keep_ideas),
                paper_transform=item.paper_transform,
                real_action_boundary=item.real_action_risk,
            )
        )
    return rows


def write_v24_reports(rows: list[V24RepoIntake], output_dir: Path) -> tuple[Path, Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "hypersmart_v24_github_intake.json"
    source_map_path = output_dir / "HYPERSMART_V24_SOURCE_TO_TARGET_FILE_MAP.md"
    module_matrix_path = output_dir / "HYPERSMART_V24_MODULE_PORTAGE_MATRIX.md"
    license_path = output_dir / "HYPERSMART_V24_LICENSE_AND_PORTAGE_AUDIT.md"
    json_path.write_text(json.dumps([asdict(row) for row in rows], indent=2, ensure_ascii=False), encoding="utf-8")
    source_map_path.write_text(format_source_to_target_map(rows), encoding="utf-8")
    module_matrix_path.write_text(format_module_portage_matrix(rows), encoding="utf-8")
    license_path.write_text(format_license_audit(rows), encoding="utf-8")
    return json_path, source_map_path, module_matrix_path, license_path


def format_source_to_target_map(rows: list[V24RepoIntake]) -> str:
    lines = [
        "# HyperSmart V24 - source to target file map",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "Runtime cible: `src/hl_observer`. Portage local paper/read-only uniquement.",
        "",
        "| Repo | Fichiers observes | Modules HyperSmart cibles | Tests cibles |",
        "|---|---|---|---|",
    ]
    for row in rows:
        files = "<br>".join(f"`{path}`" for path in row.observed_files) or "non lu / indisponible"
        targets = "<br>".join(f"`src/hl_observer/{path}`" for path in row.target_modules) or "a definir"
        tests = "<br>".join(f"`{path}`" for path in row.target_tests) or "a ajouter"
        lines.append(f"| [{row.repo}]({row.url}) | {files} | {targets} | {tests} |")
    lines.extend(
        [
            "",
            "## Regle de portage",
            "",
            "- `COPY_ADAPTED` seulement si la licence le permet et si le code est reduit, attribue et teste.",
            "- Sinon: `PORT_BEHAVIOR`, c'est-a-dire reimplementation du comportement dans les modules HyperSmart.",
            "- Aucun module source ne peut introduire d'ordre reel, de signature reelle ou de wallet connect actif.",
        ]
    )
    return "\n".join(lines)


def format_module_portage_matrix(rows: list[V24RepoIntake]) -> str:
    lines = [
        "# HyperSmart V24 - module portage matrix",
        "",
        "| Repo | Priorite | Idees a porter | Mode V24 | Action runtime |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        ideas = "<br>".join(row.ideas_to_port)
        mode = _mode_from_priority(row.priority)
        action = _action_from_policy(row)
        lines.append(f"| [{row.repo}]({row.url}) | {row.priority} | {ideas} | {mode} | {action} |")
    lines.extend(
        [
            "",
            "## Couverture actuelle",
            "",
            "- Copy wallet: modules presents dans `src/hl_observer/copy_wallet`, E2E present.",
            "- Arbitrage: modules presents dans `src/hl_observer/arbitrage`, E2E present.",
            "- Funding: modules presents dans `src/hl_observer/funding`, E2E present.",
            "- Refactor fusion run: commande active, mais certains flux restent fixture-labeled quand les donnees live manquent.",
            "- Priorite suivante: remplacer progressivement les fixtures par sources Hyperliquid read-only ou etat vide honnete.",
        ]
    )
    return "\n".join(lines)


def format_license_audit(rows: list[V24RepoIntake]) -> str:
    lines = [
        "# HyperSmart V24 - license and portage audit",
        "",
        "Objectif: eviter le copier-coller non maitrise. Les repos servent de source d'idees et de comportements; le code direct n'est admis que licence compatible.",
        "",
        "| Repo | Licence | Statut GitHub | Politique | Frontiere d'action reelle |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| [{row.repo}]({row.url}) | {row.license_spdx} ({row.license_status}) | "
            f"{row.github_status} | {row.portage_policy} | {row.real_action_boundary} |"
        )
    lines.extend(
        [
            "",
            "## Synthese",
            "",
            f"- repos_couverts={len(rows)}",
            f"- licences_permissives={sum(1 for row in rows if row.license_spdx.lower() in PERMISSIVE_LICENSES)}",
            f"- licences_a_revoir={sum(1 for row in rows if row.license_spdx.lower() not in PERMISSIVE_LICENSES)}",
            "- runtime_actif=src/hl_observer",
            "- paper_only=true",
            "- real_execution=false",
            "- future_profit_guarantee=false",
        ]
    )
    return "\n".join(lines)


def _github_metadata(owner_repo: str, *, network_read: bool) -> dict[str, Any]:
    if not network_read:
        return {
            "github_status": "network_read_disabled",
            "license_spdx": "UNKNOWN",
            "license_status": "network_read_disabled",
            "default_branch": None,
        }
    api_url = f"https://api.github.com/repos/{owner_repo}"
    try:
        payload = _get_json(api_url)
    except Exception as exc:  # noqa: BLE001 - diagnostic script, keep status explicit.
        return {
            "github_status": exc.__class__.__name__,
            "license_spdx": "NOASSERTION",
            "license_status": exc.__class__.__name__,
            "default_branch": None,
        }
    license_info = payload.get("license") if isinstance(payload, dict) else None
    spdx = str((license_info or {}).get("spdx_id") or "NOASSERTION").upper()
    return {
        "github_status": "ok",
        "license_spdx": spdx,
        "license_status": "repo_api",
        "default_branch": str(payload.get("default_branch") or "") or None,
    }


def _github_tree_files(owner_repo: str, *, default_branch: str | None, network_read: bool, max_files: int) -> list[str]:
    if not network_read or not default_branch:
        return []
    api_url = f"https://api.github.com/repos/{owner_repo}/git/trees/{default_branch}?recursive=1"
    try:
        payload = _get_json(api_url)
    except Exception:
        return []
    tree = payload.get("tree") if isinstance(payload, dict) else None
    if not isinstance(tree, list):
        return []
    scored: list[tuple[int, str]] = []
    for item in tree:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        score = _path_score(path)
        if score < 100:
            scored.append((score, path))
    scored.sort(key=lambda pair: (pair[0], pair[1].lower()))
    return [path for _, path in scored[:max_files]]


def _path_score(path: str) -> int:
    lower = path.lower()
    if lower in {"readme.md", "license", "license.md", "license.txt", "pyproject.toml", "package.json"}:
        return 0
    if lower.startswith(("src/", "app/", "bot/", "bots/", "strategies/", "strategy/", "tests/", "test/", "examples/", "config/", "configs/")):
        return 10
    if any(part in lower for part in ("copy", "wallet", "risk", "backtest", "arbitrage", "funding", "dashboard", "strategy")):
        return 20
    return 100


def _get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "HyperSmart-Observer-V24-Research-Only",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"github_http_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("github_url_error") from exc


def _owner_repo_from_url(url: str) -> str:
    marker = "github.com/"
    if marker not in url:
        return url.rstrip("/")
    tail = url.split(marker, 1)[1].strip("/")
    return "/".join(tail.split("/")[:2])


def _portage_policy(license_spdx: str, license_status: str) -> str:
    normalized = str(license_spdx or "").lower()
    if license_status == "network_read_disabled":
        return "PORT_BEHAVIOR_UNTIL_LICENSE_CHECKED"
    if normalized in PERMISSIVE_LICENSES:
        return "COPY_ADAPTED_ALLOWED_WITH_ATTRIBUTION"
    return "PORT_BEHAVIOR_NO_DIRECT_COPY"


def _mode_from_priority(priority: str) -> str:
    if priority.startswith("P0"):
        return "IMPLEMENTED_OR_FIX_NOW"
    if priority.startswith("P1"):
        return "IMPLEMENT_NEXT_VERTICAL_SLICE"
    return "MAP_AND_PORT_INCREMENTALLY"


def _action_from_policy(row: V24RepoIntake) -> str:
    targets = ", ".join(f"`{target}`" for target in row.target_modules[:2]) or "`UNASSIGNED`"
    if row.portage_policy.startswith("COPY_ADAPTED"):
        return f"copie adaptee possible vers {targets}, avec attribution et test"
    return f"porter le comportement vers {targets}, sans copie directe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="github_v24_intake")
    parser.add_argument("--network-read", action="store_true", help="Fetch public GitHub metadata and file tree.")
    parser.add_argument("--output-dir", default="docs/research")
    parser.add_argument("--max-files-per-repo", type=int, default=18)
    args = parser.parse_args(argv)
    rows = build_v24_intake(network_read=args.network_read, max_files_per_repo=args.max_files_per_repo)
    paths = write_v24_reports(rows, Path(args.output_dir))
    print("github_v24_intake=ok")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
