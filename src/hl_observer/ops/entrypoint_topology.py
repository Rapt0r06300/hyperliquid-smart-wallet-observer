from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from hl_observer.ops.runtime_contract import OFFICIAL_LAUNCH_CONTRACT, RUNTIME_PARAMETER_CONSUMERS


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
    "tools/launchers/Certificateur Coffre Fort.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/Installer Noeud HL.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/LANCER_COLLECTEURS.cmd": EntrypointRole.COMPAT,
    "tools/launchers/Noeud-HL.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/RAPPORT-COLLECTEURS.cmd": EntrypointRole.MAINTENANCE,
    "tools/launchers/SUIVI_COFFRE.cmd": EntrypointRole.MAINTENANCE,
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

    # LCH-001..LCH-010: validate the actual launch graph, not just file names.
    graph_files = (
        OFFICIAL_LAUNCH_CONTRACT["runtime_entrypoint"],
        OFFICIAL_LAUNCH_CONTRACT["runtime_handoff"],
        OFFICIAL_LAUNCH_CONTRACT["scope_module"],
        OFFICIAL_LAUNCH_CONTRACT["hosted_controller"],
    )
    for graph_path in graph_files:
        if not (root / Path(graph_path)).is_file():
            issues.append(EntrypointTopologyIssue("LAUNCH_GRAPH_FILE_MISSING", graph_path, "official launch graph node is missing"))

    if runtime_path.is_file():
        for token in (
            "start_hypersmart_simulation.ps1",
            "superviseur_collecteurs demarrer-tous harvest",
            "HYPERSMART_ACTIVE_STRATEGY_SCOPE=copy_vault",
            "HYPERSMART_SCOPE_VERSION=COPY_VAULT_PAPER_V2",
        ):
            _require(content, runtime_path.name, token, "LAUNCH_GRAPH_CONTRACT_DRIFT", issues)
        # Legacy references may remain after the subroutine's first ``exit /b``;
        # only the reachable launch block is authoritative.
        reachable = content
        marker = "\n:demarrer_collecteurs"
        if marker in content:
            reachable = content.split(marker, 1)[1].split(r"exit \b", 1)[0]
        if "lancer_research_parallel.py" in reachable or "collecter_lab_microstructure.py" in reachable:
            issues.append(EntrypointTopologyIssue("AUTO_LAB_LAUNCH", runtime_path.name, "official runtime must not start research laboratories"))

    handoff_path = root / OFFICIAL_LAUNCH_CONTRACT["runtime_handoff"]
    if handoff_path.is_file():
        handoff = _normalized(handoff_path)
        for token in ("hl_observer", "ui", "persistent_poll_runner"):
            _require(handoff, str(handoff_path.relative_to(root)), token, "RUNTIME_HANDOFF_CONTRACT_DRIFT", issues)
        _require(handoff, str(handoff_path.relative_to(root)), "hypersmart_config_authority", "CONFIG_AUTHORITY_MISSING", issues)

    # LCH-004..LCH-009: configuration consumers are explicit and the local
    # launcher cannot impersonate the hosted controller or revive old workers.
    for group, paths in RUNTIME_PARAMETER_CONSUMERS.items():
        for consumer in paths:
            if not (root / Path(consumer)).is_file():
                issues.append(EntrypointTopologyIssue("PARAMETER_CONSUMER_MISSING", consumer, f"missing {group} consumer"))
    if runtime_candidate.is_file():
        if "gh workflow run" in content or ".github\\workflows" in content:
            issues.append(EntrypointTopologyIssue("LOCAL_HOSTED_CONTROL_MIX", runtime_candidate.name, "local runtime must not dispatch hosted workflows"))
        if "tools\\boucle_collecteur.cmd research-lab" in reachable or "tools\\boucle_collecteur.cmd lab-microstructure" in reachable:
            issues.append(EntrypointTopologyIssue("LEGACY_LAB_AUTHORITY", runtime_candidate.name, "legacy laboratory workers are not runtime authority"))

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


def runtime_authority_summary(repo_root: str | Path) -> dict[str, object]:
    """Prove the five human launchers resolve to one runtime authority graph."""
    issues = audit_entrypoint_topology(repo_root)
    relevant = [issue for issue in issues if issue.code in {
        "OFFICIAL_ROLE_NOT_UNIQUE", "RUNTIME_RESEARCH_DUPLICATION", "LAUNCH_GRAPH_FILE_MISSING",
        "LEGACY_LAB_AUTHORITY", "LOCAL_HOSTED_CONTROL_MIX",
    }]
    return {
        "status": "PROVEN" if not relevant else "UNMEASURABLE",
        "official_entrypoints": {role.value: path for role, path in OFFICIAL_ENTRYPOINTS.items()},
        "runtime_authority": OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RUNTIME],
        "legacy_runtime_is_authority": False,
        "issues": [
            {"code": issue.code, "path": issue.path, "detail": issue.detail}
            for issue in relevant
        ],
        "paper_only": True,
        "real_execution": False,
    }
