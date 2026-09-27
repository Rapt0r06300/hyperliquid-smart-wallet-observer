"""SAFE-only independent module paper-PnL proof."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from hl_observer.strategies.active_scope import (
    canonical_strategy_family,
    strategy_can_materialize,
)

MODULES = ("copy_vault", "lead_lag", "cross_venue_dislocation")


@dataclass(frozen=True)
class ModulePnl:
    module: str
    gross_pnl: float
    fees: float
    slippage: float
    funding_financing: float
    net_pnl: float
    sample_size: int
    threshold_usd: float
    threshold_met: bool
    proof_of_pnl: bool


def _canonical_module(module: str) -> str:
    # Versioned aliases are inputs only; certificates use one public family name.
    return canonical_strategy_family(module)


def prove_module(
    module: str,
    rows: Iterable[Mapping[str, Any]],
    threshold_usd: float = 4.0,
) -> dict[str, Any]:
    canonical_module = _canonical_module(module)
    if canonical_module not in MODULES or not strategy_can_materialize(module):
        raise ValueError("unknown or inactive module")
    rows = list(rows)
    if not rows:
        raise ValueError("no evidence")
    if any(
        row.get("quality_status") != "SAFE"
        or not row.get("replay_compatible", False)
        for row in rows
    ):
        raise ValueError("PnL proof requires SAFE replay-compatible inputs")
    gross = sum(float(row.get("gross_pnl", 0)) for row in rows)
    fees = sum(float(row.get("fees", 0)) for row in rows)
    slippage = sum(float(row.get("slippage", 0)) for row in rows)
    funding = sum(float(row.get("funding_financing", 0)) for row in rows)
    net = gross - fees - slippage - funding
    return asdict(ModulePnl(
        canonical_module,
        gross,
        fees,
        slippage,
        funding,
        net,
        len(rows),
        threshold_usd,
        net >= threshold_usd,
        True,
    ))



def independent_module_verdict(
    module: str,
    rows: Iterable[Mapping[str, Any]],
    threshold_usd: float = 4.0,
) -> dict[str, Any]:
    """Return a fail-closed independent certificate without cross-module compensation."""
    evidence = list(rows)
    canonical_module = _canonical_module(module)
    if canonical_module not in MODULES or not strategy_can_materialize(module):
        raise ValueError("unknown or inactive module")
    if not evidence:
        verdict = {"module": canonical_module, "status": "MORE_DATA", "reason": "NO_SAFE_REPLAY_COMPATIBLE_EVIDENCE", "proof_of_pnl": False, "sample_size": 0}
    elif any(row.get("quality_status") != "SAFE" or not row.get("replay_compatible", False) for row in evidence):
        verdict = {"module": canonical_module, "status": "UNMEASURABLE", "reason": "NON_SAFE_OR_NON_REPLAY_COMPATIBLE_INPUT", "proof_of_pnl": False, "sample_size": len(evidence)}
    else:
        result = prove_module(canonical_module, evidence, threshold_usd)
        verdict = dict(result)
        verdict["status"] = "PROVEN" if result["threshold_met"] else "KILL"
        verdict["reason"] = "NET_DAILY_THRESHOLD_MET" if result["threshold_met"] else "NET_DAILY_THRESHOLD_NOT_MET"
    verdict["certificate_digest"] = hashlib.sha256(json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return verdict


def independent_module_certificates(
    evidence: Mapping[str, Iterable[Mapping[str, Any]]],
    threshold_usd: float = 4.0,
) -> dict[str, Any]:
    certificates = {
        module: independent_module_verdict(module, evidence.get(module, ()), threshold_usd)
        for module in MODULES
    }
    return {
        "schema": "alina.independent_module_pnl_certificates.v1",
        "threshold_usd_per_day": threshold_usd,
        "modules": certificates,
        "aggregate_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


def prove_all(
    evidence: Mapping[str, Iterable[Mapping[str, Any]]],
    threshold_usd: float = 4.0,
) -> dict[str, Any]:
    out = {
        module: prove_module(module, evidence[module], threshold_usd)
        for module in MODULES
    }
    return {
        "threshold_is_evaluation_only": True,
        "modules": out,
        "all_modules_independently_met": all(
            value["threshold_met"] for value in out.values()
        ),
    }
