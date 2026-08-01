"""[DATA pépite 265] PARSER GOLDEN CORPUS : on conserve de vrais messages RARES / INVALIDES / PARTIELS comme
cas de non-régression du parser. Le jour où un refacto du parser reclasse un message invalide en valide (ou
casse un cas limite déjà rencontré), la suite le détecte. Chaque cas = (message brut, résultat attendu) ; le
corpus rejoue tous les cas contre un parser candidat. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any, Callable


class CorpusGolden:
    """Registre de cas de référence. verifier(parser) exécute chaque cas et retourne les écarts (regressions).
    Un parser qui lève une exception sur un cas est compté comme échec de ce cas, jamais comme succès."""

    def __init__(self) -> None:
        self._cas: list[dict[str, Any]] = []

    def ajouter_cas(self, nom: str, message_brut: Any, attendu: Any) -> dict[str, Any]:
        self._cas.append({"nom": nom, "brut": message_brut, "attendu": attendu})
        return {"ok": True, "n_cas": len(self._cas)}

    def nombre_cas(self) -> int:
        return len(self._cas)

    def verifier(self, parser: Callable[[Any], Any]) -> dict[str, Any]:
        echecs: list[dict[str, Any]] = []
        for cas in self._cas:
            try:
                obtenu = parser(cas["brut"])
                ok = obtenu == cas["attendu"]
            except Exception as exc:                       # noqa: BLE001 (un throw = échec du cas)
                ok, obtenu = False, f"EXCEPTION:{type(exc).__name__}"
            if not ok:
                echecs.append({"nom": cas["nom"], "attendu": cas["attendu"], "obtenu": obtenu})
        return {"total": len(self._cas), "echecs": echecs, "sans_regression": len(echecs) == 0}


__all__ = ["CorpusGolden"]
