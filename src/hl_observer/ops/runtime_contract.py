"""Contrat autoritaire des flags critiques du runtime HyperSmart.

Le lanceur Windows reste le point d'assignation, mais ces valeurs sont la verite
machine-verifiable : le preflight refuse tout profil divergent avant le demarrage
du moteur. Cela evite qu'un ancien flag paper/carry soit reactive silencieusement.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

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
    "RuntimeContractResult",
    "verify_runtime_env",
    "parse_cmd_set_assignments",
]
