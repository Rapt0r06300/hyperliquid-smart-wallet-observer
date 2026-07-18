"""P2 + P3 + P4 — MONITORING : anomalies, désactivation auto, registre de cycle de vie.

P2 : alertes sur drawdown seuil, divergence de sources, décrochage. P3 : désactiver
AUTOMATIQUEMENT une stratégie dont l'edge live tombe sous son seuil (anti « zombie qui saigne »).
P4 : suivre le cycle de vie idée -> recherche -> paper -> testnet -> live -> retraite. PAPER only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ETAPES = ("IDEE", "RECHERCHE", "PAPER", "TESTNET", "LIVE", "RETRAITE")


def anomalies(*, drawdown: float = 0.0, drawdown_max: float = 100.0,
             sources_sures: bool = True, edge_decroche: bool = False) -> list[str]:
    """Liste des alertes actives (vide = tout va bien)."""
    a = []
    if float(drawdown) >= float(drawdown_max):
        a.append("DRAWDOWN_SEUIL")
    if not sources_sures:
        a.append("DIVERGENCE_SOURCES")
    if edge_decroche:
        a.append("EDGE_DECROCHE")
    return a


def doit_desactiver(edge_recent: float | None, edge_reference: float, *, fraction: float = 0.4) -> bool:
    """True si l'edge récent est tombé sous `fraction` × la référence (ou inconnu). Anti zombie."""
    if edge_recent is None:
        return True                                    # edge inconnu -> on met en observation
    if float(edge_reference) <= 0:
        return False
    return float(edge_recent) < float(fraction) * float(edge_reference)


@dataclass(slots=True)
class RegistreStrategies:
    """P4 : statut de chaque stratégie dans son cycle de vie."""
    statuts: dict[str, str] = field(default_factory=dict)

    def promouvoir(self, nom: str, etape: str) -> None:
        if str(etape).upper() not in ETAPES:
            raise ValueError("etape inconnue: %r" % (etape,))
        self.statuts[str(nom)] = str(etape).upper()

    def retraiter(self, nom: str) -> None:
        self.statuts[str(nom)] = "RETRAITE"

    def actives(self) -> list[str]:
        return [n for n, e in self.statuts.items() if e in ("PAPER", "TESTNET", "LIVE")]


__all__ = ["ETAPES", "anomalies", "doit_desactiver", "RegistreStrategies"]
