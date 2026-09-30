"""[ARB lot2 #1] WEBSOCKET EXECUTION PATH PRIORITAIRE : simuler les timings d'un canal d'ordre WS PERSISTANT plutôt
qu'un REST systématique. Un canal WS déjà ouvert évite le coût d'établissement REST et réduit fortement la latence
de soumission (esprit Nautilus REST→WS). On modélise la latence par canal pour la refléter dans le PnL paper.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

WS = "WS"
REST = "REST"


def latence_soumission_ms(*, canal: str, latence_ws_ms: float = 15.0, latence_rest_ms: float = 60.0,
                          ws_ouvert: bool = True) -> dict[str, Any]:
    """Latence modélisée : WS ouvert → latence_ws ; sinon REST (ou WS à froid retombe sur REST)."""
    c = str(canal).upper()
    if c == WS and ws_ouvert:
        return {"canal": WS, "latence_ms": float(latence_ws_ms)}
    return {"canal": REST, "latence_ms": float(latence_rest_ms),
            "raison": ("WS_FERME_FALLBACK_REST" if c == WS else "REST")}


def choisir_canal(*, ws_ouvert: bool, latence_ws_ms: float = 15.0, latence_rest_ms: float = 60.0) -> dict[str, Any]:
    """Choisit le canal le plus rapide DISPONIBLE. WS ouvert et plus rapide → WS ; sinon REST."""
    if ws_ouvert and float(latence_ws_ms) < float(latence_rest_ms):
        return {"canal": WS, "latence_ms": float(latence_ws_ms), "gain_ms": float(latence_rest_ms) - float(latence_ws_ms)}
    return {"canal": REST, "latence_ms": float(latence_rest_ms), "gain_ms": 0.0}


__all__ = ["latence_soumission_ms", "choisir_canal", "WS", "REST"]
