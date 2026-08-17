"""Garde de provenance pour la roadmap PnL canonique 1..775.

Le MASTER V6 historique (AUD/DATA/BUG, 590 tâches) reste une source technique
utile mais N'EST PAS la roadmap PnL 1..775 créée ensuite.

Deux états sont volontairement distincts :
- ``DONE`` : prétend que les 775 libellés originaux ET 775 preuves exécutables
  distinctes sont disponibles ; la garde reste extrêmement stricte ;
- ``RECOVERY_CLOSED_SOURCE_LOSS`` : clôt uniquement la recherche de la source
  littérale lorsque celle-ci est devenue irrécupérable. Cet état n'est jamais
  une preuve que les 775 optimisations techniques ont été exécutées.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ROADMAP_ID = "HYPERSMART_PNL_CANONICAL_775"
ROADMAP_TOTAL = 775
RECOVERY_CLOSED_SOURCE_LOSS = "RECOVERY_CLOSED_SOURCE_LOSS"
THEMATIC_REQUIREMENTS_PATH = "docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md"
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
REQUIRED_SOURCE_SEARCHES = {
    "GITHUB_REPOSITORY",
    "GIT_HISTORY",
    "CHAT_LIBRARY",
    "PRIOR_CONVERSATION_CONTEXT",
}

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


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _validate_source_loss(manifest: Mapping[str, Any], issues: list[str]) -> None:
    """Valide une clôture honnête de récupération, jamais une complétion technique."""
    if manifest.get("literal_source_unrecoverable") is not True:
        issues.append("SOURCE_LOSS_REQUIRES_UNRECOVERABLE_TRUE")
    if manifest.get("exact_literal_reconstruction_claimed") is not False:
        issues.append("SOURCE_LOSS_FORBIDS_LITERAL_RECONSTRUCTION_CLAIM")
    if manifest.get("technical_completion_claimed") is not False:
        issues.append("SOURCE_LOSS_FORBIDS_TECHNICAL_COMPLETION_CLAIM")
    if manifest.get("blocking") is not False:
        issues.append("SOURCE_LOSS_TERMINAL_MUST_BE_NONBLOCKING")
    if manifest.get("next_unrecovered_literal") is not None:
        issues.append("SOURCE_LOSS_TERMINAL_HAS_NO_NEXT_LITERAL")
    if manifest.get("thematic_requirements_path") != THEMATIC_REQUIREMENTS_PATH:
        issues.append("SOURCE_LOSS_REQUIRES_THEMATIC_REQUIREMENTS_PATH")
    if not _valid_sha256(manifest.get("thematic_requirements_sha256")):
        issues.append("SOURCE_LOSS_REQUIRES_VALID_THEMATIC_SHA256")
    reason = manifest.get("source_loss_reason")
    if not isinstance(reason, str) or len(reason.strip()) < 20:
        issues.append("SOURCE_LOSS_REQUIRES_EXPLICIT_REASON")

    searches = manifest.get("source_searches_completed")
    if not isinstance(searches, Sequence) or isinstance(searches, (str, bytes)):
        searches = []
    if not REQUIRED_SOURCE_SEARCHES.issubset({str(item) for item in searches}):
        issues.append("SOURCE_LOSS_REQUIRES_ALL_SOURCE_SEARCHES")

    recovered = manifest.get("recovered_literal_labels")
    recovered = recovered if isinstance(recovered, Mapping) else {}
    for number, expected in KNOWN_CANONICAL_ANCHORS.items():
        actual = recovered.get(str(number), recovered.get(number))
        if actual != expected:
            issues.append(f"SOURCE_LOSS_RECOVERED_ANCHOR_MISMATCH:{number}")
    if manifest.get("recovered_literal_count") != len(KNOWN_CANONICAL_ANCHORS):
        issues.append("SOURCE_LOSS_RECOVERED_COUNT_MISMATCH")

    # Une clôture de source ne doit jamais transporter 775 labels/proofs et se
    # faire passer implicitement pour DONE.
    if manifest.get("labels") not in (None, [], {}):
        issues.append("SOURCE_LOSS_FORBIDS_CANONICAL_LABEL_SET")
    if manifest.get("proofs") not in (None, [], {}):
        issues.append("SOURCE_LOSS_FORBIDS_775_PROOF_CLAIM")


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
    elif status == RECOVERY_CLOSED_SOURCE_LOSS:
        _validate_source_loss(manifest, issues)

    return {
        "ok": not issues,
        "roadmap_id": ROADMAP_ID,
        "roadmap_total": ROADMAP_TOTAL,
        "status": status or "UNKNOWN",
        "terminal_recovery": status == RECOVERY_CLOSED_SOURCE_LOSS and not issues,
        "technical_completion_claimed": bool(manifest.get("technical_completion_claimed")),
        "issues": issues,
    }


__all__ = [
    "KNOWN_CANONICAL_ANCHORS",
    "LEGACY_MASTER_V6_TOTAL",
    "RECOVERY_CLOSED_SOURCE_LOSS",
    "REQUIRED_SOURCE_SEARCHES",
    "ROADMAP_ID",
    "ROADMAP_TOTAL",
    "THEMATIC_REQUIREMENTS_PATH",
    "validate_manifest",
]
