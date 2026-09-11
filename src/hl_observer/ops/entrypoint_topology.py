from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class EntrypointRole(StrEnum):
    OFFICIAL_RUNTIME = "OFFICIAL_RUNTIME"
    OFFICIAL_ANALYSIS = "OFFICIAL_ANALYSIS"
    OFFICIAL_RESEARCH = "OFFICIAL_RESEARCH"
    MAINTENANCE = "MAINTENANCE"
    COMPAT = "COMPAT"
    LEGACY = "LEGACY"
    ARCHIVE = "ARCHIVE"


ENTRYPOINT_ROLES: dict[str, EntrypointRole] = {
    "ANALYSER_BACKTESTS_REPLAYS.cmd": EntrypointRole.OFFICIAL_ANALYSIS,
    "ANALYSER_DONNEES_HYPERSMART.cmd": EntrypointRole.MAINTENANCE,
    "ANALYSE_HISTORIQUE_COMPLETE.cmd": EntrypointRole.COMPAT,
    "CREER_ARCHIVE_PORTABLE.cmd": EntrypointRole.MAINTENANCE,
    "DIAGNOSTIC_LANCEUR.cmd": EntrypointRole.MAINTENANCE,
    "INSTALLER_ALINA_RUNNER_FINAL_V1.cmd": EntrypointRole.MAINTENANCE,
    "INSTALLER_ALINA_RUNNER_WINDOWS.cmd": EntrypointRole.COMPAT,
    "LANCER-CODEX-RESEARCH.cmd": EntrypointRole.MAINTENANCE,
    "LANCER-RECHERCHE-14H.cmd": EntrypointRole.COMPAT,
    "LANCER-RECHERCHE-18H.cmd": EntrypointRole.COMPAT,
    "LANCER-RECHERCHE-CONTINUE-ADMIN.cmd": EntrypointRole.COMPAT,
    "LANCER-RECHERCHE-CONTINUE.cmd": EntrypointRole.OFFICIAL_RESEARCH,
    "LANCER_COCKPIT_ALINA.cmd": EntrypointRole.COMPAT,
    "LANCER_HYPERLAB.cmd": EntrypointRole.COMPAT,
    "LANCER_HYPERSMART.cmd": EntrypointRole.OFFICIAL_RUNTIME,
    "LANCER_LABO.cmd": EntrypointRole.COMPAT,
    "LANCER_LABO_180GO.cmd": EntrypointRole.COMPAT,
    "LANCER_MICRO.cmd": EntrypointRole.COMPAT,
    "LANCER_OBJECTIF_4USD.cmd": EntrypointRole.COMPAT,
    "LANCER_REPLAY_176GO.cmd": EntrypointRole.COMPAT,
    "POUSSER-GITHUB-FORCE.cmd": EntrypointRole.LEGACY,
    "POUSSER_TOUT_LE_TRAVAIL.cmd": EntrypointRole.LEGACY,
    "PREPARER_DONNEES_HYPERSMART.cmd": EntrypointRole.MAINTENANCE,
    "PREPARER_EXPERIENCE_FULL_COLD.cmd": EntrypointRole.MAINTENANCE,
    "PREPARER_GIT_PORTABLE.cmd": EntrypointRole.MAINTENANCE,
    "PREPARER_PC_ALINA.cmd": EntrypointRole.MAINTENANCE,
    "RECETTE-LANCEUR.cmd": EntrypointRole.MAINTENANCE,
    "RECETTE-WINDOWS.cmd": EntrypointRole.MAINTENANCE,
    "REPARER_ET_POUSSER.cmd": EntrypointRole.LEGACY,
    "VERIFIER_LAB_AUTONOME_ALINA.cmd": EntrypointRole.MAINTENANCE,
}

OFFICIAL_ENTRYPOINTS = {
    EntrypointRole.OFFICIAL_RUNTIME: "LANCER_HYPERSMART.cmd",
    EntrypointRole.OFFICIAL_ANALYSIS: "ANALYSER_BACKTESTS_REPLAYS.cmd",
    EntrypointRole.OFFICIAL_RESEARCH: "LANCER-RECHERCHE-CONTINUE.cmd",
}


@dataclass(frozen=True, slots=True)
class EntrypointTopologyIssue:
    code: str
    path: str
    detail: str


def _normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("/", "\\").lower()


def _require(content: str, path: str, token: str, code: str, issues: list[EntrypointTopologyIssue]) -> None:
    if token.lower() not in content:
        issues.append(EntrypointTopologyIssue(code=code, path=path, detail=f"missing required token: {token}"))


def audit_entrypoint_topology(repo_root: str | Path) -> list[EntrypointTopologyIssue]:
    root = Path(repo_root)
    issues: list[EntrypointTopologyIssue] = []
    discovered = {path.name for path in root.glob("*.cmd") if path.is_file()}
    registered = set(ENTRYPOINT_ROLES)

    for path in sorted(discovered - registered):
        issues.append(EntrypointTopologyIssue("UNCLASSIFIED_ENTRYPOINT", path, "root .cmd is not classified"))
    for path in sorted(registered - discovered):
        issues.append(EntrypointTopologyIssue("STALE_ENTRYPOINT_REGISTRY", path, "registered .cmd is missing"))

    for role, expected in OFFICIAL_ENTRYPOINTS.items():
        actual = sorted(path for path, candidate_role in ENTRYPOINT_ROLES.items() if candidate_role == role)
        if actual != [expected]:
            issues.append(
                EntrypointTopologyIssue(
                    "OFFICIAL_ROLE_NOT_UNIQUE",
                    expected,
                    f"{role.value} must resolve uniquely to {expected}; got {actual}",
                )
            )

    common = (
        "tools\\portable_env.cmd",
        "%hypersmart_python%",
        "hl_enable_mainnet_execution=0",
        "hl_enable_testnet_execution=0",
    )
    for path in OFFICIAL_ENTRYPOINTS.values():
        candidate = root / path
        if not candidate.is_file():
            continue
        content = _normalized(candidate)
        for token in common:
            _require(content, path, token, "OFFICIAL_CONTRACT_DRIFT", issues)
        if "hl_enable_mainnet_execution=1" in content or "hl_enable_testnet_execution=1" in content:
            issues.append(EntrypointTopologyIssue("REAL_EXECUTION_DIRECTIVE", path, "official entrypoint enables execution"))

    runtime_path = root / OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RUNTIME]
    if runtime_path.is_file():
        content = _normalized(runtime_path)
        _require(content, runtime_path.name, "port_owner", "RUNTIME_SINGLE_INSTANCE_MISSING", issues)
        if "recherche_continue.py" in content:
            issues.append(EntrypointTopologyIssue("RUNTIME_RESEARCH_DUPLICATION", runtime_path.name, "runtime must not start research worker"))

    research_path = root / OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RESEARCH]
    if research_path.is_file():
        content = _normalized(research_path)
        _require(content, research_path.name, "recherche_continue.py", "RESEARCH_WORKER_MISSING", issues)
        if "hl_observer.cli run" in content:
            issues.append(EntrypointTopologyIssue("RESEARCH_SERVER_DUPLICATION", research_path.name, "research worker must not boot runtime server"))
        if "\npython " in content or "\npython.exe " in content:
            issues.append(EntrypointTopologyIssue("SYSTEM_PYTHON_FALLBACK", research_path.name, "official research launcher must use portable Python"))

    archive_path = root / "CREER_ARCHIVE_PORTABLE.cmd"
    if archive_path.is_file():
        content = _normalized(archive_path)
        for token in common:
            _require(content, archive_path.name, token, "ARCHIVE_PORTABLE_CONTRACT_DRIFT", issues)

    return issues


def render_entrypoint_topology_report(issues: list[EntrypointTopologyIssue]) -> str:
    if not issues:
        return "ENTRYPOINT_TOPOLOGY=PASS"
    lines = ["ENTRYPOINT_TOPOLOGY=FAIL"]
    lines.extend(f"- {issue.code} {issue.path}: {issue.detail}" for issue in issues)
    return "\n".join(lines)
