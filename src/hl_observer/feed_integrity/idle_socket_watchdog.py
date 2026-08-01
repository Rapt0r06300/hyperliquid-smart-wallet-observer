"""[DATA lot2 #35] IDLE-SOCKET WATCHDOG : une connexion OUVERTE mais SILENCIEUSE (aucun message depuis trop
longtemps) est considérée MORTE et doit être réouverte. Un socket qui ne renvoie plus rien sans se fermer proprement
gèle silencieusement le flux — pire qu'une déconnexion franche (Cryptofeed surveille cela). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

VIVANT = "VIVANT"
MORT = "MORT"


def etat_socket(dernier_message_ms: Any, now_ms: Any, *, timeout_ms: float) -> dict[str, Any]:
    """MORT si aucun message depuis plus de timeout_ms (à réouvrir). Horodatage inconnu → MORT (prudence :
    un socket dont on ignore l'activité est traité comme mort)."""
    if not all(isinstance(x, (int, float)) for x in (dernier_message_ms, now_ms)):
        return {"etat": MORT, "reouvrir": True, "raison": "ACTIVITE_INCONNUE"}
    silence = float(now_ms) - float(dernier_message_ms)
    if silence > float(timeout_ms):
        return {"etat": MORT, "reouvrir": True, "silence_ms": round(silence, 3), "raison": "SOCKET_SILENCIEUX"}
    return {"etat": VIVANT, "reouvrir": False, "silence_ms": round(silence, 3)}


__all__ = ["etat_socket", "VIVANT", "MORT"]
