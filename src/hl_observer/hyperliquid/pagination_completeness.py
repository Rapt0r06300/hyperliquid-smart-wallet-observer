"""AUD-117 — completude de pagination OBSERVABLE (borne honnete, jamais un silence).

La pagination des fills est BORNEE (max_pages / max_fills / page_limit) et n'invente jamais de fill.
Le risque n'est pas la borne mais de CROIRE la collecte complete alors qu'elle a ete tronquee. Ce
module classe le `stopped_reason` en COMPLET (fin naturelle) vs TRONQUE (cap atteint -> il RESTE
peut-etre des fills), et dit si l'on PEUT continuer pour atteindre la completude. Read-only.
"""
from __future__ import annotations

_COMPLET = frozenset({"empty_response", "completed", "no_more_fills", "max_pages_zero"})
_TRONQUE = frozenset({"max_pages_reached", "max_fills_reached", "page_limit_truncated",
                      "timestamp_not_progressing"})


def evaluer_completude(stopped_reason: str) -> dict:
    r = str(stopped_reason or "").strip().lower()
    if r in _COMPLET:
        return {"complet": True, "tronque": False, "peut_continuer": False, "stopped_reason": r}
    if r in _TRONQUE:
        peut = r != "timestamp_not_progressing"
        return {"complet": False, "tronque": True, "peut_continuer": peut, "stopped_reason": r}
    return {"complet": False, "tronque": True, "peut_continuer": True, "stopped_reason": r,
            "raison": "STOPPED_REASON_INCONNU"}


__all__ = ["evaluer_completude"]
