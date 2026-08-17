"""Garde de taxonomie pour la roadmap PnL canonique 1..775.

Le MASTER V6 historique (AUD/DATA/BUG, 590 tâches) reste une source technique
utile mais N'EST PAS la roadmap PnL 1..775 créée ensuite. Cette garde empêche
qu'une gate de l'ancienne taxonomie soit présentée comme preuve des 775.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ROADMAP_ID = "HYPERSMART_PNL_CANONICAL_775"
ROADMAP_TOTAL = 775
KNOWN_CANONICAL_ANCHORS = {
    301: "Interdire promotion par PnL sans coûts",
    314: "Reconstruction OPEN/ADD/REDUCE/CLOSE parfaite",
}
LEGACY_MASTER_V6_TOTAL = 590


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if manifest.get("roadmap_id") != ROADMAP_ID:
        issues.append("WRONG_ROADMAP_ID")
    if manifest.get("total") != ROADMAP_TOTAL:
        issues.append("WRONG_ROADMAP_TOTAL")
    if manifest.get("legacy_master_v6_equivalent") is not False:
        issues.append("LEGACY_V6_MUST_NOT_BE_DECLARED_EQUIVALENT")

    anchors = manifest.get("anchors")
    anchors = anchors if isinstance(anchors, Mapping) else {}
    for number, expected in KNOWN_CANONICAL_ANCHORS.items():
        actual = anchors.get(str(number), anchors.get(number))
        if actual != expected:
            issues.append(f"CANONICAL_ANCHOR_MISMATCH:{number}")

    status = str(manifest.get("status") or "").upper()
    if status == "DONE":
        labels = manifest.get("labels")
        proofs = manifest.get("proofs")
        labels = labels if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)) else []
        proofs = proofs if isinstance(proofs, Mapping) else {}
        if len(labels) != ROADMAP_TOTAL:
            issues.append("DONE_REQUIRES_775_LITERAL_LABELS")
        expected_numbers = set(range(1, ROADMAP_TOTAL + 1))
        proof_numbers: set[int] = set()
        for key, value in proofs.items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                continue
            if value:
                proof_numbers.add(number)
        if proof_numbers != expected_numbers:
            issues.append("DONE_REQUIRES_775_EXECUTABLE_PROOFS")

    return {
        "ok": not issues,
        "roadmap_id": ROADMAP_ID,
        "roadmap_total": ROADMAP_TOTAL,
        "status": status or "UNKNOWN",
        "issues": issues,
    }


__all__ = [
    "KNOWN_CANONICAL_ANCHORS",
    "LEGACY_MASTER_V6_TOTAL",
    "ROADMAP_ID",
    "ROADMAP_TOTAL",
    "validate_manifest",
]
