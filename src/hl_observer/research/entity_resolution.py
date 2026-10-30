"""[AUD-285/286] Resolution d'ENTITES (fusionner par Union-Find les wallets d'un meme acteur
cross-protocole a partir de liens declares -> ne pas compter un acteur comme N wallets independants,
sinon le crowding est faux) et PROVENANCE des labels (chaque label porte source + asof, jamais un
label orphelin non tracable). stdlib pure, 0 reseau."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"
MEASURABLE = "MEASURABLE"


def _link_fields(link: Any) -> tuple[str, str, str | None, float | None, str | None]:
    """Read a declared equivalence without treating an unproven link as fact."""
    if isinstance(link, Mapping):
        left = link.get("wallet_a", link.get("a"))
        right = link.get("wallet_b", link.get("b"))
        source = str(link.get("source") or "").strip() or None
        raw_asof = link.get("asof")
        evidence_id = str(link.get("evidence_id") or "").strip() or None
    else:
        try:
            left, right = link
        except (TypeError, ValueError):
            return "", "", None, None, None
        source = None
        raw_asof = None
        evidence_id = None
    asof = (
        float(raw_asof)
        if isinstance(raw_asof, (int, float))
        and not isinstance(raw_asof, bool)
        and math.isfinite(float(raw_asof))
        else None
    )
    return str(left or "").strip(), str(right or "").strip(), source, asof, evidence_id


def resoudre_entites(
    liens: Sequence[tuple[str, str] | Mapping[str, Any]],
    *,
    cutoff_asof: float | None = None,
) -> dict:
    """Resolve declared links while exposing provenance and point-in-time limits.

    Two-item tuples remain accepted for compatibility with historical fixtures,
    but they are deliberately reported as ``UNMEASURABLE`` because their
    source and observation time are absent.  A link is admissible for a
    measurable result only when it carries ``source`` and finite ``asof``;
    links after ``cutoff_asof`` are rejected rather than leaking the future.
    """
    parent: dict[str, str] = {}

    def trouver(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unir(a: str, b: str) -> None:
        ra, rb = trouver(a), trouver(b)
        if ra != rb:
            parent[ra] = rb

    rejected: list[dict[str, Any]] = []
    accepted = 0
    measurable = True
    for index, link in enumerate(liens):
        a, b, source, asof, evidence_id = _link_fields(link)
        reason = None
        if not a or not b:
            reason = "MISSING_WALLET"
        elif a == b:
            reason = "SELF_LINK"
        elif not source or asof is None:
            measurable = False
            reason = "MISSING_POINT_IN_TIME_PROVENANCE"
        elif cutoff_asof is not None and asof > cutoff_asof:
            reason = "LINK_AFTER_CUTOFF"
        if reason is not None:
            if reason == "MISSING_POINT_IN_TIME_PROVENANCE" and a and b and a != b:
                # Keep legacy topology available for diagnostics, but never
                # label it as independent measured evidence.
                unir(a, b)
            rejected.append({"index": index, "reason": reason, "evidence_id": evidence_id})
            continue
        unir(a, b)
        accepted += 1
    groupes: dict[str, set] = {}
    for x in list(parent):
        groupes.setdefault(trouver(x), set()).add(x)
    entites = sorted(sorted(g) for g in groupes.values())
    return {
        "n_entites": len(entites),
        "entites": entites,
        "accepted_links": accepted,
        "rejected_links": rejected,
        "provenance_complete": measurable and not rejected,
        "measurement_status": MEASURABLE if measurable and not rejected else UNMEASURABLE,
        "cutoff_asof": cutoff_asof,
    }


def provenance_label(label: str, *, source: str, asof: float) -> dict:
    """Un label SANS provenance est inexploitable (on ne peut pas le remonter a un rapport). La source
    est OBLIGATOIRE ; l'asof (point-in-time) evite d'utiliser un label anachronique."""
    if not source:
        raise ValueError("un label doit porter une source (provenance obligatoire)")
    return {"label": label, "source": source, "asof": asof, "tracable": True}
