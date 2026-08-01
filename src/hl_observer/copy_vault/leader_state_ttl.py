"""[COPY-VAULT #69] LEADER-STATE TTL : l'equity et les positions du leader ont CHACUNE leur âge maximal acceptable.
Dimensionner une copie sur une equity périmée ou des positions périmées produit une réplication fausse. Si l'un des
deux dépasse son TTL, l'état leader est INVALIDE et on ne copie pas. Âge inconnu → invalide. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any


def etat_valide(*, age_equity_ms: Any, age_positions_ms: Any, ttl_equity_ms: float,
                ttl_positions_ms: float) -> dict[str, Any]:
    """Valide seulement si equity ET positions sont chacune dans leur propre TTL. Un âge inconnu ou hors TTL
    invalide l'état complet (fail-closed : on ne dimensionne pas sur du périmé)."""
    def _ok(age: Any, ttl: float) -> bool:
        return isinstance(age, (int, float)) and 0 <= float(age) <= float(ttl)

    eq_ok = _ok(age_equity_ms, ttl_equity_ms)
    pos_ok = _ok(age_positions_ms, ttl_positions_ms)
    perimes = [n for n, ok in (("equity", eq_ok), ("positions", pos_ok)) if not ok]
    valide = eq_ok and pos_ok
    return {"valide": bool(valide), "equity_ok": eq_ok, "positions_ok": pos_ok, "perimes": perimes,
            "raison": ("OK" if valide else "ETAT_LEADER_PERIME")}


__all__ = ["etat_valide"]
