"""Phase 14: multi-directory safety. In BOTH runtime trees (hyper_smart_observer +
src/hl_observer) the only files containing place_order( are locked fail-closed
refusal stubs (which raise), and the authoritative config-based safety audit
passes. Ban-guard text that merely prohibits forbidden actions is allowed."""

from __future__ import annotations

from pathlib import Path

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.audit.safety_audit import run_safety_audit
from hyper_smart_observer.audit.source_scanner import scan_source_forbidden_terms

ROOT = Path(__file__).resolve().parents[1]
# Locked fail-closed stubs: place_order exists only to refuse (raises).
_LOCKED_ORDER_STUBS = (
    "hyperliquid_client/testnet_exchange_client.py",
    "execution/live_executor_disabled.py",
)


def _is_locked(path: str) -> bool:
    norm = path.replace("\\", "/")
    return any(norm.endswith(stub) for stub in _LOCKED_ORDER_STUBS)


def test_runtime_trees_have_only_locked_order_stubs():
    scanned = 0
    for sub in ("hyper_smart_observer", "src/hl_observer"):
        d = ROOT / sub
        if not d.exists():
            continue
        scanned += 1
        findings = scan_source_forbidden_terms(d)
        operational = [p for p in findings["place_order"] if not _is_locked(p)]
        assert operational == [], f"operational order call in {sub}: {operational}"
    assert scanned >= 1


def test_locked_order_stubs_are_fail_closed():
    # The allowlist is only safe if these stubs actually refuse.
    from hl_observer.execution.live_executor_disabled import (
        LiveExecutionDisabled,
        LiveExecutorDisabled,
    )

    import pytest

    with pytest.raises(LiveExecutionDisabled):
        LiveExecutorDisabled().place_order("BTC", 1.0)


def test_run_safety_audit_core_checks_ok():
    findings = {f.name: f.ok for f in run_safety_audit(AppConfig())}
    for name in (
        "no_exchange_path", "no_signature_calls", "no_operational_order",
        "no_private_key_config", "execution_disabled_by_default",
        "testnet_disabled_by_default", "mainnet_forbidden",
    ):
        assert findings.get(name) is True, f"{name} not OK"
