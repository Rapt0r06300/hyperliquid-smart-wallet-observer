from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD
from hl_observer.backtesting.copy_vault_snapshot_contract import (
    NOT_PROVEN,
    PROVEN,
    verify_snapshot_contract,
)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot() -> dict[str, object]:
    digest_fields = {
        "selection_digest": "0" * 64,
        "engine_source_sha256": "1" * 64,
        "campaign_config_sha256": "2" * 64,
        "source_catalog_sha256": "3" * 64,
        "source_asset_inventory_sha256": "4" * 64,
    }
    artifacts = {
        field: {"field": field}
        for field in ("ledger", "equity", "costs", "metrics", "tests", "report")
    }
    artifacts["restoration_receipt"] = {"status": "RESTORABLE", "sha256": "7" * 64}
    snapshot = {
        "schema_version": "hypersmart.copy_vault_restoration_snapshot.v1",
        "restoration_status": "READY",
        "restoration_missing_requirements": [],
        "lineage": digest_fields | {"source_asset_inventory_count": 15456},
        "search": {
            "campaign_config": {"family": "copy_vault", "schema": "v1"},
            "proposal_seed": 0,
            "temporal_windows": {"train_start_ms": 10, "train_end_ms": 20},
            "paper_capital_usd": PAPER_EQUITY_USD,
            "global_trial_count": 7,
        },
        "trial_accounting": {
            "trial_number": 7,
            "attempt_receipt_sha256": "5" * 64,
            "trial_receipt_sha256": "6" * 64,
        },
        "candidate_freeze": {
            "freeze": {"parameters": {"core_notional_usd": 20.0}},
        },
        "artifacts": artifacts,
        "artifacts_sha256": {field: _canonical_sha256(value) for field, value in artifacts.items()},
        "paper_read_only": True,
        "real_execution": False,
        "restore_started": False,
        "source_untouched": True,
    }
    snapshot["candidate_freeze"]["freeze"]["parameters_sha256"] = _canonical_sha256(  # type: ignore[index]
        snapshot["candidate_freeze"]["freeze"]["parameters"]  # type: ignore[index]
    )
    snapshot["restoration_snapshot_sha256"] = _canonical_sha256(snapshot)
    return snapshot


def test_complete_canonical_h95_snapshot_is_proven() -> None:
    report = verify_snapshot_contract(_snapshot())

    assert report["status"] == PROVEN
    assert report["missing"] == []
    assert report["paper_read_only"] is True
    assert report["real_execution"] is False


def test_missing_restore_artifact_is_not_filled_or_proven() -> None:
    snapshot = deepcopy(_snapshot())
    del snapshot["artifacts"]["restoration_receipt"]  # type: ignore[index]

    report = verify_snapshot_contract(snapshot)

    assert report["status"] == NOT_PROVEN
    assert "artifacts.restoration_receipt" in report["missing"]


def test_non_restorable_status_and_non_paper_mode_are_rejected() -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["restoration_status"] = "UNMEASURABLE"
    snapshot["real_execution"] = True

    report = verify_snapshot_contract(snapshot)

    assert report["status"] == NOT_PROVEN
    assert "restoration_status" in report["invalid"]
    assert "real_execution" in report["invalid"]


def test_empty_source_inventory_is_not_restorable() -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["lineage"]["source_asset_inventory_count"] = 0  # type: ignore[index]

    report = verify_snapshot_contract(snapshot)

    assert report["status"] == NOT_PROVEN
    assert "lineage.source_asset_inventory_count" in report["invalid"]


def test_le_capital_exige_est_celui_que_le_LABO_ECRIT_et_non_200_USD() -> None:
    """17/11/2026 — le contrat exigeait encore 200,0 USD, montant historique et inactif.

    Le labo écrit `PAPER_CAPITAL_USD = PAPER_EQUITY_USD` (350,0 USD) dans chaque instantané de
    restauration. Avec l'ancienne règle, tout instantané émis par le labo actuel était refusé par
    son propre validateur, et ce fichier de test ne passait que parce que sa fixture portait 200.
    """
    from hl_observer.backtesting import copy_vault_local_lab

    assert copy_vault_local_lab.PAPER_CAPITAL_USD == PAPER_EQUITY_USD, (
        "le labo et le contrat doivent lire le capital paper a la MEME source")
    snapshot = _snapshot()
    snapshot["search"]["paper_capital_usd"] = copy_vault_local_lab.PAPER_CAPITAL_USD  # type: ignore[index]
    assert verify_snapshot_contract(snapshot)["status"] == PROVEN


def test_un_instantane_au_capital_HISTORIQUE_de_200_USD_est_refuse() -> None:
    snapshot = _snapshot()
    snapshot["search"]["paper_capital_usd"] = 200.0  # type: ignore[index]
    receipt = verify_snapshot_contract(snapshot)
    assert receipt["status"] == NOT_PROVEN
    assert "search.paper_capital_usd" in json.dumps(receipt)


def test_un_capital_BOOLEEN_n_est_pas_un_montant() -> None:
    """`True == 1` en Python : un booléen ne doit jamais passer pour un capital."""
    snapshot = _snapshot()
    snapshot["search"]["paper_capital_usd"] = True  # type: ignore[index]
    assert verify_snapshot_contract(snapshot)["status"] == NOT_PROVEN
