"""Gate local fail-closed des optimisations pré-run 001 -> 100.

Ce gate ne lance aucune collecte et aucun backtest. Il vérifie que le HEAD possède les
preuves de code/tests 001-100, que les drapeaux d'exécution réelle sont désarmés, que
le dépôt est identifiable, que la configuration ne contient pas de wallet/clé et que
les incidents runtime bloquants déjà présents ne sont pas masqués.

La lecture est non-mutante ; seule l'écriture explicite du rapport de sortie crée un
fichier. Aucun dossier runtime n'est créé simplement pour constater son absence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from hl_observer.audit.pre_run_001_100 import inspect_coverage
from hl_observer.runtime.protections import JournalIncidents, manifeste_execution
from hl_observer.runtime.research_guardrails import verifier_absence_wallet, verifier_plan_websockets

SCHEMA_VERSION = "hypersmart.pre_run_guard_001_100.v2"
DEFAULT_OUTPUT = Path("runtime") / "reports" / "pre_run_001_100.json"

EXECUTION_FLAGS = (
    "HL_ENABLE_MAINNET_EXECUTION",
    "HL_ENABLE_TESTNET_EXECUTION",
    "REAL_MAINNET_TRADING",
    "TESTNET_EXECUTION_ENABLED",
    "HYPERSMART_ENABLE_REAL_ORDERS",
    "ENABLE_REAL_ORDERS",
)
SECRET_ENV_FIELDS = (
    "private_key",
    "mnemonic",
    "seed",
    "wallet_address",
    "signer",
    "api_secret",
    "secret_key",
)


def _armed(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _execution_flag_report(environ: Mapping[str, str]) -> dict[str, Any]:
    armed = [name for name in EXECUTION_FLAGS if _armed(environ.get(name))]
    return {
        "armed": armed,
        "all_disabled": not armed,
        "values": {name: environ.get(name) for name in EXECUTION_FLAGS},
    }


def _wallet_report(environ: Mapping[str, str]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    lower_env = {str(key).lower(): value for key, value in environ.items()}
    for field in SECRET_ENV_FIELDS:
        for key, value in lower_env.items():
            if field in key and str(value or "").strip():
                config[field] = "PRESENT"
                break
    return verifier_absence_wallet(config)


def build_report(
    root: Path | str,
    *,
    environ: Mapping[str, str] | None = None,
    require_clean_git: bool = False,
) -> dict[str, Any]:
    base = Path(root).resolve()
    env = dict(os.environ if environ is None else environ)
    coverage = inspect_coverage(base)
    execution = _execution_flag_report(env)
    wallet = _wallet_report(env)
    provenance = manifeste_execution(base, gate="001-100")
    incidents = JournalIncidents(base / "runtime" / "operational", create=False).resume()
    websocket_guard = verifier_plan_websockets(1, nouvelles_par_minute=1, subscriptions=10, users_uniques=1)

    blockers: list[str] = []
    warnings: list[str] = []
    if not coverage["all_code_present"]:
        blockers.append("OPTIMIZATIONS_001_100_EVIDENCE_MISSING")
    if not execution["all_disabled"]:
        blockers.append("REAL_OR_TESTNET_EXECUTION_FLAG_ARMED")
    if not wallet["conforme"]:
        blockers.append("WALLET_OR_SECRET_CONFIGURATION_PRESENT")
    if not websocket_guard["conforme"]:
        blockers.append("WEBSOCKET_PLAN_OUTSIDE_GUARDRAILS")
    if incidents["promotion_interdite"]:
        blockers.append("BLOCKING_RUNTIME_INCIDENT_PRESENT")
    if provenance["git_head"] is None:
        blockers.append("GIT_HEAD_UNKNOWN")
    if require_clean_git and provenance["git_dirty"] is not False:
        blockers.append("GIT_TREE_NOT_PROVEN_CLEAN")
    elif provenance["git_dirty"] is True:
        warnings.append("GIT_TREE_DIRTY")
    elif provenance["git_dirty"] is None:
        warnings.append("GIT_TREE_STATE_UNKNOWN")

    status = "BLOCKED" if blockers else ("PASS_WITH_WARNINGS" if warnings else "PASS")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "coverage": {
            "n_items": coverage["n_items"],
            "n_code_present": coverage["n_code_present"],
            "n_missing": coverage["n_missing"],
            "missing_ids": coverage["missing_ids"],
            "verified_by_presence": False,
        },
        "execution_flags": execution,
        "wallet_guard": wallet,
        "websocket_guard": websocket_guard,
        "runtime_incidents": incidents,
        "provenance": provenance,
        "paper_only": True,
        "real_execution": False,
    }


def write_report(report: Mapping[str, Any], output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate pré-run HyperSmart optimisations 001-100")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--require-clean-git", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args.root, require_clean_git=args.require_clean_git)
    output = Path(args.output)
    if not output.is_absolute():
        output = Path(args.root) / output
    write_report(report, output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
