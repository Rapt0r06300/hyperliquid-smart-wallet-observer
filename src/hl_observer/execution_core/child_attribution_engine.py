"""[ALL pépite 247] CHILD ATTRIBUTION ENGINE : après un fill AGRÉGÉ (#246), répartir quantité / frais / slippage aux
intents SOURCES de manière DÉTERMINISTE (au prorata de leur contribution). Sans attribution, on ne sait plus quel
module a gagné/perdu quoi ; avec, chaque module reçoit sa part exacte. La somme des parts égale le total (conservation).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def attribuer(contributions: Sequence[dict[str, Any]], *, qte_totale: Any, frais_total: Any,
              slippage_total: Any) -> dict[str, Any]:
    """Répartit qté/frais/slippage au prorata de |contribution| de chaque intent source. Somme des |contrib| nulle
    ou totaux invalides → UNMEASURABLE (on n'invente pas de répartition)."""
    if not all(isinstance(x, (int, float)) for x in (qte_totale, frais_total, slippage_total)):
        return {"parts": UNMEASURABLE, "raison": "TOTAUX_INVALIDES"}
    poids = [(c.get("module"), abs(float(c.get("montant", 0.0)))) for c in contributions
             if isinstance(c.get("montant"), (int, float))]
    somme = sum(w for _, w in poids)
    if somme <= 0:
        return {"parts": UNMEASURABLE, "raison": "CONTRIBUTIONS_NULLES"}
    parts = []
    for mod, w in poids:
        f = w / somme
        parts.append({"module": mod, "part": round(f, 6),
                      "qte": round(float(qte_totale) * f, 12), "frais": round(float(frais_total) * f, 8),
                      "slippage": round(float(slippage_total) * f, 8)})
    return {"parts": parts, "controle_qte": round(sum(p["qte"] for p in parts), 10)}


__all__ = ["attribuer", "UNMEASURABLE"]
