from __future__ import annotations

import json

from hl_observer.signals.porte_copy_whitelist import (
    CHEMIN_CERTIFICATION_VNEXT,
    MOTIF_CERTIFICATION_VNEXT_INVALIDE,
    signal_copy_autorise,
)
from hl_observer.simulation import vnext_promotion_protocol as protocol

_REQUIRED_PROOFS = (
    "costs_complete",
    "liquidability_complete",
    "provenance_complete",
    "positions_flat",
    "economic_reconciliation_ok",
    "validation_without_recalibration",
    "temporal_disjointness_ok",
    "forward_post_freeze_complete",
    "placebo_complete",
)


def _ecrire_whitelist(root) -> None:
    whitelist = root / "runtime" / "data" / "copy_whitelist.json"
    whitelist.parent.mkdir(parents=True, exist_ok=True)
    whitelist.write_text(
        json.dumps({"genere_ts": 1_000.0, "gardes": [{"adresse": "0xabc"}]}),
        encoding="utf-8",
    )


def _preuve_vnext(*, family: str = "copy_vault") -> dict[str, object]:
    manifest = protocol.build_freeze_manifest(
        family=family,
        freeze_candidate={"variant": "test"},
        dataset_fingerprint="d" * 64,
        config={"capital_usd": 1000.0, "paper_read_only": True},
        frozen_at_ms=1_000,
    )
    freeze_hash = str(manifest["freeze_hash"])
    return {
        "certification_status": "CERTIFICATION_READY",
        "freeze_manifest": manifest,
        "freeze_hash": freeze_hash,
        "post_freeze_oos_consumed": True,
        "consumed_freeze_hash": freeze_hash,
        "paper_read_only": True,
        "real_execution": False,
        "frozen_at_ms": 1_000,
        "temporal_windows": {
            "validation": {"start_ms": 1_100, "end_ms": 1_200},
            "oos": {"start_ms": 1_200, "end_ms": 1_300},
            "forward": {"start_ms": 1_300, "end_ms": 1_400},
            "placebo": {"start_ms": 1_400, "end_ms": 1_500},
        },
        **{field: True for field in _REQUIRED_PROOFS},
    }


def _ecrire_campagne(root, *, family: str = "copy_vault") -> None:
    path = root / CHEMIN_CERTIFICATION_VNEXT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"family": "copy_vault", "vnext_promotion": _preuve_vnext(family=family)}),
        encoding="utf-8",
    )


def test_whitelist_legacy_seule_ne_peut_pas_autoriser(tmp_path) -> None:
    _ecrire_whitelist(tmp_path)

    autorise, motif = signal_copy_autorise(["0xabc"], root=tmp_path, now=1_001.0)

    assert autorise is False
    assert motif == MOTIF_CERTIFICATION_VNEXT_INVALIDE


def test_preuve_vnext_d_une_autre_famille_ne_peut_pas_autoriser_copy_vault(tmp_path) -> None:
    _ecrire_whitelist(tmp_path)
    _ecrire_campagne(tmp_path, family="lead_lag")

    assert signal_copy_autorise(["0xabc"], root=tmp_path, now=1_001.0) == (
        False,
        MOTIF_CERTIFICATION_VNEXT_INVALIDE,
    )


def test_whitelist_restrictive_et_preuve_vnext_copy_valide_autorisent(tmp_path) -> None:
    _ecrire_whitelist(tmp_path)
    _ecrire_campagne(tmp_path)

    assert signal_copy_autorise(["0xabc"], root=tmp_path, now=1_001.0) == (True, None)
