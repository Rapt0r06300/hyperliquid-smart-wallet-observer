"""[ARB #40] CONVERSION TTL : un taux de conversion (USDC/USDT/EUR…) porte son PROPRE âge maximal. Un taux figé il
y a trop longtemps n'est pas fiable pour chiffrer un arb — même s'il « existe ». Au-delà du TTL, la conversion est
UNMEASURABLE, jamais réutilisée telle quelle. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def taux_valide(age_ms: Any, *, ttl_ms: float) -> dict[str, Any]:
    """Vrai seulement si 0 ≤ age ≤ ttl. Âge inconnu → invalide (on ne suppose jamais un taux frais)."""
    if not isinstance(age_ms, (int, float)) or float(age_ms) < 0:
        return {"valide": False, "raison": "AGE_INCONNU"}
    ok = float(age_ms) <= float(ttl_ms)
    return {"valide": bool(ok), "age_ms": float(age_ms), "ttl_ms": float(ttl_ms),
            "raison": ("OK" if ok else "TAUX_PERIME")}


def convertir_avec_ttl(montant: Any, taux: Any, *, age_ms: Any, ttl_ms: float) -> dict[str, Any]:
    """Applique le taux SEULEMENT s'il est dans son TTL ; sinon UNMEASURABLE (jamais un taux périmé)."""
    v = taux_valide(age_ms, ttl_ms=ttl_ms)
    if not v["valide"]:
        return {"valeur": UNMEASURABLE, "refuse": True, "raison": v["raison"]}
    if not all(isinstance(x, (int, float)) for x in (montant, taux)) or float(taux) <= 0:
        return {"valeur": UNMEASURABLE, "refuse": True, "raison": "ENTREE_INVALIDE"}
    return {"valeur": round(float(montant) * float(taux), 10), "refuse": False, "raison": "OK"}


__all__ = ["taux_valide", "convertir_avec_ttl", "UNMEASURABLE"]
