from __future__ import annotations

from pathlib import Path

from hl_observer.audit.simulation_realism_audit import audit_paper_ledger_snapshot
from hl_observer.simulation.paper_ledger import PaperLedger


def test_simulation_ledger_exposes_realism_fields():
    ledger = PaperLedger(starting_balance_usdc=1000)
    ledger.open_position(coin="SOL", side="LONG", notional_usdc=50, fill_price=25, timestamp_ms=1)
    ledger.mark_to_market({"SOL": 24}, timestamp_ms=2)
    snapshot = ledger.snapshot()

    for key in (
        "cash_balance_usdc",
        "realized_pnl_usdc",
        "unrealized_pnl_usdc",
        "fees_paid_usdc",
        "funding_net_usdc",
        "equity_usdc",
        "drawdown_usdc",
        "reconciliation",
    ):
        assert key in snapshot
    assert snapshot["reconciliation"]["ok"] is True
    audit = audit_paper_ledger_snapshot(snapshot)
    assert audit.ok


def test_simulation_realism_audit_detects_missing_reconciliation():
    audit = audit_paper_ledger_snapshot({"equity_usdc": 1000})

    assert not audit.ok
    assert any(item.startswith("MISSING_LEDGER_FIELDS") for item in audit.findings)


def test_phase0_docs_exist():
    # 2026-07-10: docs consolidees (demande Flo "supprime le maximum de .md"). Les anciens
    # docs Phase-0 (ARCHITECTURE_PHASE_0, LEGACY_ISOLATION_PLAN, release/PHASE_0_REPORT,
    # research/GITHUB_IDEAS_TO_MODULES) ont ete fusionnes dans le doc maitre. On verifie
    # desormais l'existence de la doc canonique consolidee (recuperables via git si besoin).
    required = [
        "CLAUDE.md",
        "OBJECTIF.md",
        "docs/ETAT_ET_FEUILLE_DE_ROUTE.md",
        "docs/CONFIG_FLAGS.md",
    ]
    for path in required:
        assert Path(path).exists(), path
