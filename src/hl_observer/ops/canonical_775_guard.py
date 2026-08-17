"""Garde de taxonomie pour la roadmap PnL canonique 1..775.

Le MASTER V6 historique (AUD/DATA/BUG, 590 tâches) reste une source technique
utile mais N'EST PAS la roadmap PnL 1..775 créée ensuite. Cette garde empêche
qu'une gate de l'ancienne taxonomie, des libellés factices ou une preuve
générique réutilisée 775 fois soient présentés comme preuve des 775.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ROADMAP_ID = "HYPERSMART_PNL_CANONICAL_775"
ROADMAP_TOTAL = 775
KNOWN_CANONICAL_ANCHORS = {
    301: "Interdire promotion par PnL sans coûts",
    314: "Reconstruction OPEN/ADD/REDUCE/CLOSE parfaite",
    315: "Retraits/dépôts non confondus avec PnL",
    316: "Wallet/vault identity stable",
    317: "Backfill complet",
    318: "Pagination userFillsByTime",
    319: "Déduplication fills",
    320: "Fraîcheur du leader",
}
LEGACY_MASTER_V6_TOTAL = 590

_PLACEHOLDER_LABELS = {
    "x",
    "todo",
    "tbd",
    "placeholder",
    "unknown",
    "inconnu",
    "unrecovered",
    "a recuperer",
    "à récupérer",
    "non recupere",
    "non récupéré",
}


def _literal_label(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    clean = " ".join(value.strip().split())
    if not clean:
        return False
    lowered = clean.casefold()
    return lowered not in _PLACEHOLDER_LABELS and not lowered.startswith(("todo:", "tbd:", "placeholder:"))


def _proof_descriptor(value: Any) -> str | None:
    """Normalise une preuve exécutable sans imposer pytest comme seul moteur."""
    if isinstance(value, str):
        clean = " ".join(value.strip().split())
        return clean or None
    if isinstance(value, Mapping):
        for key in ("command", "test", "workflow", "proof", "path"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return f"{key}:{' '.join(candidate.strip().split())}"
    return None


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
        elif not all(_literal_label(label) for label in labels):
            issues.append("DONE_REQUIRES_LITERAL_NON_PLACEHOLDER_LABELS")
        else:
            for number, expected in KNOWN_CANONICAL_ANCHORS.items():
                if labels[number - 1] != expected:
                    issues.append(f"DONE_LITERAL_LABEL_MISMATCH:{number}")

        expected_numbers = set(range(1, ROADMAP_TOTAL + 1))
        proof_numbers: set[int] = set()
        descriptors: list[str] = []
        invalid_proofs = 0
        for key, value in proofs.items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                continue
            descriptor = _proof_descriptor(value)
            if descriptor is None:
                invalid_proofs += 1
                continue
            proof_numbers.add(number)
            descriptors.append(descriptor)
        if proof_numbers != expected_numbers or invalid_proofs:
            issues.append("DONE_REQUIRES_775_EXECUTABLE_PROOFS")
        if len(descriptors) != ROADMAP_TOTAL or len(set(descriptors)) != ROADMAP_TOTAL:
            issues.append("DONE_REQUIRES_775_DISTINCT_EXECUTABLE_PROOFS")

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
