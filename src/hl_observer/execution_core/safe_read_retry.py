"""[ALL #94] SAFE READ RETRY : pour les LECTURES réseau UNIQUEMENT — backoff exponentiel + jitter + max de
tentatives. On ne re-tente JAMAIS à l'aveugle une SOUMISSION dont l'état est inconnu (elle est peut-être déjà
passée ; il faut réconcilier, pas renvoyer). Le jitter est déterministe (dérivé d'un seed) pour rester testable et
reproductible. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
from typing import Any

LECTURE = "LECTURE"
SOUMISSION = "SOUMISSION"


def _jitter_frac(n: int, seed: int) -> float:
    """Fraction de jitter déterministe dans [0,1) dérivée de (n, seed) — pas de hasard réel (reproductible)."""
    h = hashlib.sha1(("%d:%d" % (int(n), int(seed))).encode("utf-8")).hexdigest()
    return (int(h[:8], 16) % 1000) / 1000.0


def delais_backoff(max_retries: int, *, base_ms: float = 100.0, max_ms: float = 5000.0,
                   jitter_frac: float = 0.2, seed: int = 0) -> list[float]:
    """Suite de délais : base × 2^(n) plafonné à max_ms, plus un jitter déterministe ≤ jitter_frac × délai."""
    out = []
    for n in range(int(max_retries)):
        d = min(float(max_ms), float(base_ms) * (2.0 ** n))
        d = d * (1.0 + float(jitter_frac) * _jitter_frac(n, seed))
        out.append(round(d, 3))
    return out


def peut_retry(type_operation: Any, *, tentative: int, max_retries: int, etat_connu: bool = True) -> dict[str, Any]:
    """Autorise le retry seulement pour une LECTURE sous le plafond de tentatives. Une SOUMISSION à l'état inconnu
    ne se retente jamais (→ réconcilier)."""
    t = str(type_operation).upper()
    if t == SOUMISSION and not etat_connu:
        return {"retry": False, "raison": "SOUMISSION_ETAT_INCONNU_RECONCILIER"}
    if t != LECTURE:
        return {"retry": False, "raison": "RETRY_RESERVE_AUX_LECTURES"}
    if int(tentative) >= int(max_retries):
        return {"retry": False, "raison": "MAX_RETRIES_ATTEINT"}
    return {"retry": True, "raison": "OK"}


__all__ = ["delais_backoff", "peut_retry", "LECTURE", "SOUMISSION"]
