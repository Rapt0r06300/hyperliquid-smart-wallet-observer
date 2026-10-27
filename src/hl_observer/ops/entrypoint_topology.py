from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class EntrypointRole(StrEnum):
    OFFICIAL_RUNTIME = "OFFICIAL_RUNTIME"
    OFFICIAL_ANALYSIS = "OFFICIAL_ANALYSIS"
    OFFICIAL_COLLECTION = "OFFICIAL_COLLECTION"
    OFFICIAL_GIT_SYNC = "OFFICIAL_GIT_SYNC"
    OFFICIAL_DATA_SYNC = "OFFICIAL_DATA_SYNC"
    OFFICIAL_RESEARCH = "OFFICIAL_RESEARCH"
    MAINTENANCE = "MAINTENANCE"
    COMPAT = "COMPAT"
    LEGACY = "LEGACY"
    ARCHIVE = "ARCHIVE"


ENTRYPOINT_ROLES: dict[str, EntrypointRole] = {
    # The five human-facing entrypoints stay at the repository root.
    "ALINA_SYNC_COMPLETE.cmd": EntrypointRole.OFFICIAL_DATA_SYNC,
    "LANCER_COLLECTEURS_COPY_VAULT.cmd": EntrypointRole.OFFICIAL_COLLECTION,
    "LANCER_HYPERSMART.cmd": EntrypointRole.OFFICIAL_RUNTIME,
    "LANCER_LAB_QUANT_COPY_VAULT.cmd": EntrypointRole.OFFICIAL_ANALYSIS,
    "POUSSER-GITHUB-FORCE.cmd": EntrypointRole.OFFICIAL_GIT_SYNC,
    # AlinaSync is also a supported root entrypoint, separate from the four main CMD roles.
    # Remaining commands are support/compatibility tools kept under tools/launchers/.
    "tools/launchers/Alina-restore.cmd": EntrypointRole.COMPAT,
    "tools/launchers/ANALYSE_HISTORIQUE_COMPLETE.cmd": EntrypointRole.COMPAT,
    "tools/launchers/ANALYSER_BACKTESTS_REPLAYS.cmd": EntrypointRole.COMPAT,
    "tools/launchers/ANALYSER_DONNEES_HYPERSMART.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/BACKUP_LOCAL_ALINA.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/CREER_ARCHIVE_PORTABLE.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/CREER_RELEASE_COMPLETE.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/DIAGNOSTIC_LANCEUR.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/INSTALLER_ALINA_RUNNER_FINAL_V1.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/INSTALLER_ALINA_RUNNER_WINDOWS.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER-CODEX-RESEARCH.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/LANCER-RECHERCHE-14H.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER-RECHERCHE-18H.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER-RECHERCHE-CONTINUE-ADMIN.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER-RECHERCHE-CONTINUE.cmd": EntrypointRole.OFFICIAL_RESEARCH,
    "tools/launchers/LANCER_COCKPIT_ALINA.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER_HYPERLAB.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER_LABO.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER_LABO_180GO.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER_MICRO.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER_OBJECTIF_4USD.cmd": EntrypointRole.COMPAT,
    "tools/launchers/LANCER_REPLAY_176GO.cmd": EntrypointRole.COMPAT,
    "tools/launchers/POUSSER_TOUT_LE_TRAVAIL.cmd": EntrypointRole.LEGACY,
    "tools/launchers/PREPARER_DONNEES_HYPERSMART.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/PREPARER_EXPERIENCE_FULL_COLD.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/PREPARER_GIT_PORTABLE.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/PREPARER_PC_ALINA.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/RECETTE-LANCEUR.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/RECETTE-WINDOWS.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/REPARER_ET_POUSSER.cmd": EntrypointRole.LEGACY,
    "tools/launchers/RESTORE_ALINA.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/VERIFIER_LAB_AUTONOME_ALINA.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/VERIFIER_REPARER_L2_LOCAL.cmd": EntrypointRole.MAINTENANCE,
}

ROOT_ENTRYPOINTS = {
    "ALINA_SYNC_COMPLETE.cmd",
    "LANCER_COLLECTEURS_COPY_VAULT.cmd",
    "LANCER_HYPERSMART.cmd",
    "LANCER_LAB_QUANT_COPY_VAULT.cmd",
    "POUSSER-GITHUB-FORCE.cmd",
}

OFFICIAL_ENTRYPOINTS = {
    EntrypointRole.OFFICIAL_RUNTIME: "LANCER_HYPERSMART.cmd",
    EntrypointRole.OFFICIAL_ANALYSIS: "LANCER_LAB_QUANT_COPY_VAULT.cmd",
    EntrypointRole.OFFICIAL_COLLECTION: "LANCER_COLLECTEURS_COPY_VAULT.cmd",
    EntrypointRole.OFFICIAL_GIT_SYNC: "POUSSER-GITHUB-FORCE.cmd",
    EntrypointRole.OFFICIAL_DATA_SYNC: "ALINA_SYNC_COMPLETE.cmd",
    EntrypointRole.OFFICIAL_RESEARCH: "tools/launchers/LANCER-RECHERCHE-CONTINUE.cmd",
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
    for path in sorted(discovered - ROOT_ENTRYPOINTS):
        issues.append(EntrypointTopologyIssue("UNEXPECTED_ROOT_ENTRYPOINT", path, "support .cmd must live under tools/launchers/"))
    for path in sorted(ROOT_ENTRYPOINTS - discovered):
        issues.append(EntrypointTopologyIssue("MISSING_ROOT_ENTRYPOINT", path, "required root launcher is missing"))
    registered = set(ENTRYPOINT_ROLES)
    for path in sorted(registered):
        if not (root / Path(path)).is_file():
            issues.append(EntrypointTopologyIssue("STALE_ENTRYPOINT_REGISTRY", path, "registered .cmd is missing"))
    nested = {
        path.relative_to(root).as_posix()
        for path in (root / "tools" / "launchers").glob("*.cmd")
        if path.is_file()
    }
    nested_registered = {path for path in registered if path.startswith("tools/launchers/")}
    for path in sorted(nested - nested_registered):
        issues.append(EntrypointTopologyIssue("UNCLASSIFIED_SUPPORT_ENTRYPOINT", path, "support .cmd is not classified"))
    for path in sorted(nested_registered - nested):
        issues.append(EntrypointTopologyIssue("STALE_SUPPORT_ENTRYPOINT", path, "registered support .cmd is missing"))

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
    runtime_contract = OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RUNTIME]
    runtime_candidate = root / runtime_contract
    if runtime_candidate.is_file():
        content = _normalized(runtime_candidate)
        for token in common:
            _require(content, runtime_contract, token, "OFFICIAL_CONTRACT_DRIFT", issues)
    for role in (EntrypointRole.OFFICIAL_ANALYSIS, EntrypointRole.OFFICIAL_COLLECTION):
        path = OFFICIAL_ENTRYPOINTS[role]
        candidate = root / path
        if candidate.is_file():
            content = _normalized(candidate)
            for token in ("hl_enable_mainnet_execution=0", "hl_enable_testnet_execution=0"):
                _require(content, path, token, "OFFICIAL_CONTRACT_DRIFT", issues)
    for path in (runtime_contract, OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_ANALYSIS],
                 OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_COLLECTION]):
        candidate = root / path
        if candidate.is_file():
            content = _normalized(candidate)
            if "hl_enable_mainnet_execution=1" in content or "hl_enable_testnet_execution=1" in content:
                issues.append(EntrypointTopologyIssue("REAL_EXECUTION_DIRECTIVE", path, "official entrypoint enables execution"))

    runtime_path = runtime_candidate
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

    archive_path = root / "tools/launchers/CREER_ARCHIVE_PORTABLE.cmd"
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
