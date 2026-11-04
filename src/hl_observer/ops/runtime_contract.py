"""Contrat autoritaire des flags critiques du runtime HyperSmart.

Le lanceur Windows reste le point d'assignation, mais ces valeurs sont la verite
machine-verifiable : le preflight refuse tout profil divergent avant le demarrage
du moteur. Cela evite qu'un ancien flag paper/carry soit reactive silencieusement.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import os
from typing import Mapping

from hl_observer.strategies.active_scope import OFFICIAL_SCOPE_FAMILY, OFFICIAL_SCOPE_VERSION

# Flags qui doivent deja etre presents lorsque preflight_lanceur s'execute.
PREFLIGHT_RUNTIME_FLAGS = MappingProxyType({
    "HL_ENV": "paper",
    "HL_ENABLE_MAINNET_EXECUTION": "0",
    "HL_ENABLE_TESTNET_EXECUTION": "0",
    "HYPERSMART_MODE": "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW",
    "HYPERSMART_STARTUP_PROFILE": "harvest",
    # La voie v1 ecrivait dans le ledger UI historique. Elle est quarantinee :
    # seul EXPERIMENTAL_PAPER v2 porte le cross-venue actif.
    "HYPERSMART_ARB_DISLOCATION_PAPER": "0",
    "HYPERSMART_EXPERIMENTAL_PAPER": "1",
    "HYPERSMART_EXPLORATORY_PAPER": "1",
    "HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE": "0",
    "HYPERSMART_FUNDING_ARB_PAPER": "0",
    "HYPERSMART_V9_PIPELINE_AUTHORITATIVE": "1",
    "HYPERSMART_V12_GATE_AUTHORITATIVE": "1",
    "HYPERSMART_RESET_ON_LAUNCH": "0",
    "HYPERSMART_ENABLE_AUX_IA": "0",
    "HYPERSMART_ENABLE_AUX_STREAM": "1",
    "HYPERSMART_ACTIVE_STRATEGY_SCOPE": OFFICIAL_SCOPE_FAMILY,
    "HYPERSMART_SCOPE_VERSION": OFFICIAL_SCOPE_VERSION,
})

# Ces flags sont assignes plus loin dans le .cmd, mais avant tout writer/economic
# runtime. Les tests de contrat les verrouillent egalement contre toute resurrection
# du carry historique.
POST_PREFLIGHT_RUNTIME_FLAGS = MappingProxyType({
    "HYPERSMART_CARRY_HYPE_PAPER": "0",
    "HYPERSMART_CARRY_ETAPE2": "0",
    "HYPERSMART_CARRY_DISABLED": "1",
})

CRITICAL_RUNTIME_FLAGS = MappingProxyType({
    **dict(PREFLIGHT_RUNTIME_FLAGS),
    **dict(POST_PREFLIGHT_RUNTIME_FLAGS),
})

# Machine-readable contract for the two collection lanes.  The workflow tests
# bind this contract to the checked-in GitHub-hosted controller/worker files so
# a renamed job or a missing durable handoff cannot silently become a local
# assumption.
RESUMABLE_COLLECTION_CONTRACT = MappingProxyType({
    "controller_workflow": ".github/workflows/resumable-campaign-controller.yml",
    "worker_workflow": ".github/workflows/resumable-campaign-worker.yml",
    "collection_jobs": ("copy_work", "other_work"),
    "controller_outputs": (
        "copy_matrix",
        "copy_count",
        "other_matrix",
        "other_count",
        "phase",
        "phase_epoch",
    ),
    "worker_phase_guards": ("--expected-phase", "--expected-epoch"),
    "durable_worker_markers": (
        "Claim durable campaign lease",
        "Persist collection data or analysis evidence (SAFE certification first)",
        "id: durable",
    ),
})

OFFICIAL_LAUNCH_CONTRACT = MappingProxyType({
    "runtime_entrypoint": "LANCER_HYPERSMART.cmd",
    "runtime_handoff": "tools/start_hypersmart_simulation.ps1",
    "ui_service": "-m hl_observer ui",
    "collector_dispatch": "hl_observer.ops.superviseur_collecteurs demarrer-tous harvest",
    "collector_stop": "hl_observer.ops.superviseur_collecteurs arreter",
    "scope_module": "src/hl_observer/strategies/active_scope.py",
    "scope_family": OFFICIAL_SCOPE_FAMILY,
    "scope_version": OFFICIAL_SCOPE_VERSION,
    "hosted_controller": ".github/workflows/resumable-campaign-controller.yml",
    "mode": "paper",
})

# Machine-readable consumer inventory for the launch parameters.  The inventory
# is deliberately small and canonical: it describes consumers, not another
# configuration source, and is audited for file existence at startup checks.
RUNTIME_PARAMETER_CONSUMERS = MappingProxyType({
    "scope": (
        "src/hl_observer/strategies/active_scope.py",
        "src/hl_observer/ops/preflight_lanceur.py",
    ),
    "orchestration": (
        "tools/start_hypersmart_simulation.ps1",
        "src/hl_observer/ops/global_observer_pipeline.py",
    ),
    "collection": (
        "src/hl_observer/ops/superviseur_collecteurs.py",
        "src/hl_observer/runtime/persistent_poll_runner.py",
    ),
    "inventory": (
        "tools/scan_economic_hardcodes.py",
        "src/hl_observer/ops/scope_flag_inventory.py",
    ),
})

ORCHESTRATION_BOUNDARY = MappingProxyType({
    "launcher": "LANCER_HYPERSMART.cmd",
    "orchestrator": "tools/start_hypersmart_simulation.ps1",
    "quant_engine": "src/hl_observer/ops/global_observer_pipeline.py",
    "hosted_controller": ".github/workflows/resumable-campaign-controller.yml",
    "paper_only": True,
})

# A child process must not inherit an operator's permissive experiment or
# execution switch.  The deny list is intentionally explicit and small: it is
# a safety boundary, not a generic environment scrubber.
CHILD_ENV_DENY_KEYS = frozenset({
    "HYPERSMART_ACTIVE_STRATEGIES",
    "HYPERSMART_ENABLE_MAINNET_EXECUTION",
    "HYPERSMART_ENABLE_TESTNET_EXECUTION",
    "REAL_MAINNET_TRADING",
    "TESTNET_EXECUTION_ENABLED",
    "START_MAINNET_EXECUTION",
    "START_TESTNET_EXECUTION",
    "HYPERSMART_EXECUTION_ENDPOINT",
    "HYPERSMART_PRIVATE_KEY",
    "HL_PRIVATE_KEY",
    "PRIVATE_KEY",
})

CHILD_RUNTIME_OVERRIDES = MappingProxyType({
    **dict(CRITICAL_RUNTIME_FLAGS),
    "REAL_MAINNET_TRADING": "false",
    "TESTNET_ONLY": "true",
    "HYPERSMART_ANALYSIS_LOCAL_ONLY": "1",
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
})


@dataclass(frozen=True)
class RuntimeContractResult:
    ok: bool
    mismatches: tuple[str, ...]

    @property
    def detail(self) -> str:
        return "profil runtime conforme" if self.ok else "; ".join(self.mismatches)


def verify_runtime_env(
    env: Mapping[str, str],
    *,
    expected: Mapping[str, str] = PREFLIGHT_RUNTIME_FLAGS,
) -> RuntimeContractResult:
    """Compare l'environnement au contrat exact, sans valeur implicite.

    Un flag absent est un echec : un runtime critique ne doit jamais dependre de
    l'environnement parent ou d'un ancien terminal Windows.
    """
    mismatches: list[str] = []
    for key, wanted in expected.items():
        actual = env.get(key)
        if actual is None:
            mismatches.append(f"{key}=MISSING (attendu {wanted})")
            continue
        got = str(actual).strip()
        if got != wanted:
            mismatches.append(f"{key}={got!r} (attendu {wanted!r})")
    return RuntimeContractResult(not mismatches, tuple(mismatches))


def build_safe_child_environment(
    parent: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a deny-by-default paper environment for a child process.

    Parent values are retained only when they are not known control-plane
    overrides.  Canonical runtime flags are then written explicitly, so an
    absent or permissive parent variable cannot activate execution or another
    strategy family in the child.
    """
    environment = dict(parent if parent is not None else os.environ)
    for key in CHILD_ENV_DENY_KEYS:
        environment.pop(key, None)
    environment.update(CHILD_RUNTIME_OVERRIDES)
    return environment


def verify_safe_child_environment(env: Mapping[str, str]) -> RuntimeContractResult:
    """Verify both the canonical flags and the absence of inherited overrides."""
    mismatches = list(verify_runtime_env(env).mismatches)
    for key in sorted(CHILD_ENV_DENY_KEYS):
        if key in env and key not in CHILD_RUNTIME_OVERRIDES:
            mismatches.append(f"{key}=INHERITED_OVERRIDE")
    if env.get("REAL_MAINNET_TRADING") != "false":
        mismatches.append("REAL_MAINNET_TRADING must be false")
    if env.get("TESTNET_ONLY") != "true":
        mismatches.append("TESTNET_ONLY must be true")
    return RuntimeContractResult(not mismatches, tuple(mismatches))


def parse_cmd_set_assignments(text: str) -> dict[str, list[str]]:
    """Extrait les `set \"KEY=VALUE\"` actifs d'un lanceur .cmd.

    Les lignes REM sont ignorees. Plusieurs valeurs pour une cle sont conservees
    afin que les tests puissent detecter un double source-of-truth contradictoire.
    """
    out: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("rem "):
            continue
        low = line.lower()
        if not low.startswith('set "') or not line.endswith('"'):
            continue
        body = line[5:-1]
        if "=" not in body:
            continue
        key, value = body.split("=", 1)
        out.setdefault(key, []).append(value)
    return out


__all__ = [
    "PREFLIGHT_RUNTIME_FLAGS",
    "POST_PREFLIGHT_RUNTIME_FLAGS",
    "CRITICAL_RUNTIME_FLAGS",
    "RESUMABLE_COLLECTION_CONTRACT",
    "OFFICIAL_LAUNCH_CONTRACT",
    "RUNTIME_PARAMETER_CONSUMERS",
    "ORCHESTRATION_BOUNDARY",
    "CHILD_ENV_DENY_KEYS",
    "CHILD_RUNTIME_OVERRIDES",
    "RuntimeContractResult",
    "verify_runtime_env",
    "build_safe_child_environment",
    "verify_safe_child_environment",
    "parse_cmd_set_assignments",
]
