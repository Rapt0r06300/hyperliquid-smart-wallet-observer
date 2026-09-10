from __future__ import annotations

import pytest

from hl_observer.backtesting.copy_vault_hypothesis_registry import (
    ACTIVE_CAUSAL_CONSENSUS,
    KILLED_SIMPLE_WHITELIST,
    copy_vault_hypothesis_disposition,
    copy_vault_hypothesis_ledger,
    require_runnable_copy_vault_hypothesis,
)
from hl_observer.backtesting.copy_vault_vnext_train import MECHANISM


def test_killed_simple_whitelist_reste_historique_et_non_runnable() -> None:
    disposition = copy_vault_hypothesis_disposition(KILLED_SIMPLE_WHITELIST)

    assert disposition["status"] == "KILLED"
    assert disposition["evidence_class"] == "HISTORICAL_NEGATIVE_EVIDENCE"
    assert disposition["replacement"] == ACTIVE_CAUSAL_CONSENSUS
    with pytest.raises(RuntimeError, match="status=KILLED"):
        require_runnable_copy_vault_hypothesis(KILLED_SIMPLE_WHITELIST)


def test_hypothese_inconnue_fail_closed_jusqua_disposition_explicite() -> None:
    disposition = copy_vault_hypothesis_disposition("copy_vault_future_unreviewed")

    assert disposition["status"] == "UNREGISTERED"
    with pytest.raises(RuntimeError, match="status=UNREGISTERED"):
        require_runnable_copy_vault_hypothesis("copy_vault_future_unreviewed")


def test_selecteur_vnext_courant_est_exactement_hypothese_active_enregistree() -> None:
    disposition = require_runnable_copy_vault_hypothesis(MECHANISM)

    assert MECHANISM == ACTIVE_CAUSAL_CONSENSUS
    assert disposition["status"] == "ACTIVE"
    ledger = copy_vault_hypothesis_ledger()
    assert [row["hypothesis_id"] for row in ledger] == sorted(
        row["hypothesis_id"] for row in ledger
    )
    assert {row["status"] for row in ledger} == {"ACTIVE", "KILLED"}
