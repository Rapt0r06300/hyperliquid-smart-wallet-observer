"""[ARB #47] PERSISTENT UNFINISHED EPISODES : après un crash/restart, un arbitrage INCOMPLET (résidu nu, hedge en
attente) doit être repris à partir de son ÉTAT RÉEL enregistré, pas oublié. Un épisode oublié = une exposition
fantôme qui ne sera jamais débouclée. Le journal distingue les épisodes terminés des inachevés et rejoue ces
derniers. Pur, 0 réseau, 0 ordre réel (persistance simulée en mémoire).
"""
from __future__ import annotations

from typing import Any

# états considérés comme TERMINÉS (rien à reprendre)
_TERMINES = {"HEDGED", "FLAT", "CLOSED", "SETTLED", "TERMINE"}


class JournalEpisodes:
    """Journal d'épisodes avec leur état réel. `episodes_inacheves()` = tout ce qui n'est pas terminé ;
    `reprendre()` rejoue l'état réel enregistré au lieu de le perdre."""

    def __init__(self) -> None:
        self._etats: dict[str, dict[str, Any]] = {}

    def enregistrer(self, episode_id: str, *, etat: str, **contexte: Any) -> None:
        """Persiste (simulé) l'état réel courant d'un épisode. Écrase la version précédente du même épisode."""
        self._etats[str(episode_id)] = {"episode_id": str(episode_id), "etat": str(etat).upper(),
                                        "contexte": dict(contexte)}

    def episodes_inacheves(self) -> list[dict[str, Any]]:
        """Épisodes dont l'état enregistré n'est PAS terminal — à reprendre après restart."""
        return [dict(v) for v in self._etats.values() if v["etat"] not in _TERMINES]

    def reprendre(self, episode_id: str) -> dict[str, Any]:
        """Reprend un épisode depuis son état RÉEL. Inconnu → NON_RECUPERABLE (jamais supposé terminé)."""
        v = self._etats.get(str(episode_id))
        if v is None:
            return {"reprenable": False, "raison": "EPISODE_INCONNU"}
        if v["etat"] in _TERMINES:
            return {"reprenable": False, "etat": v["etat"], "raison": "DEJA_TERMINE"}
        return {"reprenable": True, "etat": v["etat"], "contexte": dict(v["contexte"]),
                "raison": "REPRENDRE_DEPUIS_ETAT_REEL"}


__all__ = ["JournalEpisodes"]
