from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hl_observer.analysis.v19_repo_matrix import V19_REPO_FUSION_ITEMS  # noqa: E402


PERMISSIVE_LICENSES = {
    "mit",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "mpl-2.0",
}


@dataclass(frozen=True, slots=True)
class RepoIntake:
    repo: str
    url: str
    priority: str
    license_spdx: str
    license_status: str
    direct_code_copy_policy: str
    integration_mode: str
    hyper_smart_targets: tuple[str, ...]
    feature_ideas: tuple[str, ...]
    required_tests: tuple[str, ...]
    safety_boundary: str


@dataclass(frozen=True, slots=True)
class FusionQueueItem:
    repo: str
    url: str
    priority: str
    queue_rank: int
    action_now: str
    code_policy: str
    integration_mode: str
    first_target_module: str
    required_test: str
    ideas_to_port: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]


def build_intake(*, network_read: bool = False) -> list[RepoIntake]:
    rows: list[RepoIntake] = []
    license_cache: dict[str, tuple[str, str]] = {}
    for item in V19_REPO_FUSION_ITEMS:
        spdx, status = _license_for_url(item.url, network_read=network_read, cache=license_cache)
        copy_policy, mode = _integration_policy(spdx, status)
        rows.append(
            RepoIntake(
                repo=item.name,
                url=item.url,
                priority=item.priority,
                license_spdx=spdx,
                license_status=status,
                direct_code_copy_policy=copy_policy,
                integration_mode=mode,
                hyper_smart_targets=tuple(item.target_modules),
                feature_ideas=tuple(item.keep_ideas),
                required_tests=tuple(item.target_tests),
                safety_boundary=item.real_action_risk,
            )
        )
    return rows


def build_fusion_queue(rows: list[RepoIntake]) -> list[FusionQueueItem]:
    prioritized = sorted(rows, key=_queue_sort_key)
    queue: list[FusionQueueItem] = []
    rank = 1
    for row in prioritized:
        if not (row.priority.startswith("P0") or row.priority.startswith("P1")):
            continue
        target = row.hyper_smart_targets[0] if row.hyper_smart_targets else "UNASSIGNED"
        test = row.required_tests[0] if row.required_tests else "ADD_TARGETED_TEST"
        queue.append(
            FusionQueueItem(
                repo=row.repo,
                url=row.url,
                priority=row.priority,
                queue_rank=rank,
                action_now=_action_for_policy(row.direct_code_copy_policy),
                code_policy=row.direct_code_copy_policy,
                integration_mode=row.integration_mode,
                first_target_module=target,
                required_test=test,
                ideas_to_port=tuple(row.feature_ideas),
                acceptance_criteria=(
                    "Hyperliquid/read-only input only",
                    "PaperEngine or backtest output only",
                    "Decision/evidence log updated",
                    "No private key, no signature, no real external order",
                    "Targeted test passes",
                ),
            )
        )
        rank += 1
    return queue


def write_intake_reports(rows: list[RepoIntake], output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "hypersmart_v19_github_code_intake.json"
    md_path = output_dir / "HYPERSMART_V19_GITHUB_CODE_INTAKE.md"
    queue_path = output_dir / "HYPERSMART_V19_GITHUB_FUSION_QUEUE.md"
    json_path.write_text(json.dumps([asdict(row) for row in rows], indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(format_intake_markdown(rows), encoding="utf-8")
    queue_path.write_text(format_fusion_queue_markdown(build_fusion_queue(rows)), encoding="utf-8")
    return json_path, md_path, queue_path


def format_intake_markdown(rows: list[RepoIntake]) -> str:
    lines = [
        "# HyperSmart V19 - GitHub code intake",
        "",
        "Objectif: fusionner les meilleures idees des repos dans HyperSmart, en local paper/read-only.",
        "",
        "Regle: le copier-coller direct de code n'est autorise que si la licence le permet, avec attribution et adaptation testee. Sinon, on reimplemente le pattern.",
        "",
        "| Repo | Licence | Politique code | Mode integration | Targets | Tests |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        targets = "<br>".join(row.hyper_smart_targets)
        tests = "<br>".join(row.required_tests)
        lines.append(
            f"| [{row.repo}]({row.url}) | {row.license_spdx} ({row.license_status}) | "
            f"{row.direct_code_copy_policy} | {row.integration_mode} | {targets} | {tests} |"
        )
    lines.extend(
        [
            "",
            "## Prochaine fusion utile",
            "",
            "1. Prioriser les repos P0/P1.",
            "2. Pour chaque repo permissif, importer seulement des fonctions isolees apres attribution et tests.",
            "3. Pour les licences inconnues/non permissives, reimplementer l'algorithme sans copier le texte source.",
            "4. Brancher les idees dans HyperSmart via RiskEngine, PaperEngine, evidence_chain et dashboard.",
            "5. Garder toute action externe reelle interdite; seules lecture publique, simulation locale et backtest sont autorises.",
            "",
            "## Controle",
            "",
            f"- repo_count={len(rows)}",
            "- local_paper_only=true",
            "- direct_external_execution=false",
            "- private_key_required=false",
            "- future_profit_guarantee=false",
        ]
    )
    return "\n".join(lines)


def format_fusion_queue_markdown(queue: list[FusionQueueItem]) -> str:
    lines = [
        "# HyperSmart V19 - GitHub fusion queue",
        "",
        "Cette file transforme la recherche GitHub en travaux codables, testables et locaux.",
        "",
        "Important: elle ne promet pas de PnL positif. Elle force seulement une fusion disciplinee: signal -> risque -> PaperEngine -> evidence -> tests.",
        "",
        "| Rang | Repo | Priorite | Action | Module cible | Test obligatoire | Idees a porter |",
        "|---:|---|---|---|---|---|---|",
    ]
    for item in queue:
        ideas = "<br>".join(item.ideas_to_port)
        lines.append(
            f"| {item.queue_rank} | [{item.repo}]({item.url}) | {item.priority} | {item.action_now} | "
            f"`{item.first_target_module}` | `{item.required_test}` | {ideas} |"
        )
    lines.extend(
        [
            "",
            "## Definition of done par repo",
            "",
            "Chaque item est considere integre seulement si:",
            "",
            "- le module cible contient une adaptation Hyperliquid/local-paper du pattern;",
            "- le test obligatoire passe;",
            "- la decision apparait dans l'evidence_chain ou le no-trade ledger;",
            "- la simulation n'utilise aucune donnee fake et aucun ordre externe;",
            "- le PnL reste un resultat mesure, jamais une garantie.",
            "",
            f"queue_count={len(queue)}",
        ]
    )
    return "\n".join(lines)


def _license_for_url(url: str, *, network_read: bool, cache: dict[str, tuple[str, str]]) -> tuple[str, str]:
    owner_repo = _owner_repo_from_url(url)
    if owner_repo in cache:
        return cache[owner_repo]
    if not network_read:
        result = ("UNKNOWN", "network_read_disabled")
        cache[owner_repo] = result
        return result
    api_url = f"https://api.github.com/repos/{owner_repo}/license"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "HyperSmart-Observer-Research-Only",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        license_info = payload.get("license") if isinstance(payload, dict) else None
        spdx = str((license_info or {}).get("spdx_id") or "NOASSERTION").upper()
        status = "github_api"
    except urllib.error.HTTPError as exc:
        spdx = "NOASSERTION"
        status = f"http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        spdx = "NOASSERTION"
        status = exc.__class__.__name__
    result = (spdx, status)
    cache[owner_repo] = result
    return result


def _owner_repo_from_url(url: str) -> str:
    marker = "github.com/"
    if marker not in url:
        return url.rstrip("/")
    tail = url.split(marker, 1)[1].strip("/")
    return "/".join(tail.split("/")[:2])


def _integration_policy(spdx: str, status: str) -> tuple[str, str]:
    normalized = spdx.lower()
    if status == "network_read_disabled":
        return (
            "NO_DIRECT_COPY_UNTIL_LICENSE_CHECKED",
            "REIMPLEMENT_PATTERN_FIRST",
        )
    if normalized in PERMISSIVE_LICENSES:
        return (
            "DIRECT_COPY_POSSIBLE_WITH_ATTRIBUTION_AND_TESTS",
            "ADAPT_OR_REIMPLEMENT_IN_SMALL_MODULES",
        )
    if normalized in {"noassertion", "other", "none", "unlicense"}:
        return (
            "NO_DIRECT_COPY_BY_DEFAULT",
            "REIMPLEMENT_PATTERN_ONLY",
        )
    return (
        "LICENSE_REVIEW_REQUIRED_BEFORE_COPY",
        "REIMPLEMENT_OR_KEEP_RESEARCH_ONLY",
    )


def _queue_sort_key(row: RepoIntake) -> tuple[int, int, str]:
    priority_rank = 0 if row.priority.startswith("P0") else 1 if row.priority.startswith("P1") else 2
    policy_rank = 0 if row.direct_code_copy_policy.startswith("DIRECT_COPY") else 1
    return (priority_rank, policy_rank, row.repo.lower())


def _action_for_policy(policy: str) -> str:
    if policy.startswith("DIRECT_COPY"):
        return "ADAPTER_CODE_PERMISSIF_AVEC_ATTRIBUTION"
    if policy.startswith("LICENSE_REVIEW"):
        return "REIMPLEMENTER_PATTERN_SANS_COPIER"
    return "REIMPLEMENTER_PATTERN_VERIFIER_SOURCE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="github_fusion_intake")
    parser.add_argument("--network-read", action="store_true", help="Fetch GitHub license metadata only.")
    parser.add_argument("--output-dir", default="docs/research", help="Report output directory.")
    args = parser.parse_args(argv)
    rows = build_intake(network_read=args.network_read)
    json_path, md_path, queue_path = write_intake_reports(rows, Path(args.output_dir))
    print(f"github_fusion_intake_json={json_path}")
    print(f"github_fusion_intake_md={md_path}")
    print(f"github_fusion_queue_md={queue_path}")
    print(format_intake_markdown(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
