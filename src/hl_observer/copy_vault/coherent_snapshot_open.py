"""[COPY-VAULT lot2 #43] OPEN/ADD EXIGE SNAPSHOT COHÉRENT DE MÊME VERSION : dimensionner une OUVERTURE/AJOUT exige
que l'equity et les positions viennent du MÊME snapshot (même version, cf. #41). Mélanger l'equity de T1 avec la
position de T2 produit un ratio faux. Une réduction/fermeture peut tolérer un léger décalage, pas une ouverture.
Versions différentes → OPEN/ADD refusé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def open_autorise(*, version_equity: Any, version_positions: Any) -> dict[str, Any]:
    """OPEN/ADD autorisé seulement si les deux versions existent ET sont identiques. Sinon refus (snapshot
    incohérent, equity et position de moments différents)."""
    if version_equity is None or version_positions is None:
        return {"autorise": False, "raison": "VERSION_MANQUANTE"}
    ok = version_equity == version_positions
    return {"autorise": bool(ok), "version": (version_equity if ok else None),
            "raison": ("OK" if ok else "SNAPSHOT_INCOHERENT_VERSIONS_DIFFERENTES")}


def snapshot_version_receipt(*, version_equity: Any, version_positions: Any) -> dict[str, Any]:
    """Expose a paper/read-only version gate for OPEN/ADD sizing."""

    if version_equity is None or version_positions is None:
        return {"status": "PROVEN", "open_allowed": False, "reason": "VERSION_MISSING", "paper_read_only": True}
    same = version_equity == version_positions
    return {"status": "PROVEN", "open_allowed": same,
            "reason": "VERSION_MATCH" if same else "VERSION_DIVERGENCE", "paper_read_only": True}


__all__ = ["open_autorise", "snapshot_version_receipt"]
