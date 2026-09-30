"""[AUD-195] Attentes de donnees CENTRALISEES : un seul endroit declare les contraintes (non-null,
plage, ensemble autorise) et VALIDE les lignes -> les regles ne sont plus eparpillees ni
contradictoires. stdlib pure, 0 reseau ; deny-by-default sur champ requis manquant."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


class ContratDonnees:
    """Contrat de donnees CENTRALISE : on declare les attentes une fois, `valider` rend TOUTES les
    violations (ligne, champ, regle). Centralise = pas de regles dupliquees et divergentes ailleurs."""

    def __init__(self) -> None:
        self._regles: list[dict] = []

    def non_null(self, champ: str) -> "ContratDonnees":
        self._regles.append({"champ": champ, "type": "non_null"})
        return self

    def dans_plage(self, champ: str, mini: float, maxi: float) -> "ContratDonnees":
        self._regles.append({"champ": champ, "type": "plage", "min": mini, "max": maxi})
        return self

    def dans_ensemble(self, champ: str, valeurs: Sequence) -> "ContratDonnees":
        self._regles.append({"champ": champ, "type": "ensemble", "valeurs": set(valeurs)})
        return self

    def valider(self, lignes: Sequence[Mapping[str, Any]]) -> dict:
        violations = []
        for i, ligne in enumerate(lignes):
            for r in self._regles:
                champ = r["champ"]
                present = champ in ligne
                val = ligne.get(champ)
                if r["type"] == "non_null":
                    if not present or val is None:
                        violations.append({"ligne": i, "champ": champ, "regle": "non_null"})
                elif not present or val is None:
                    violations.append({"ligne": i, "champ": champ, "regle": "manquant"})
                elif r["type"] == "plage":
                    if not (r["min"] <= val <= r["max"]):
                        violations.append({"ligne": i, "champ": champ, "regle": "plage", "valeur": val})
                elif r["type"] == "ensemble":
                    if val not in r["valeurs"]:
                        violations.append({"ligne": i, "champ": champ, "regle": "ensemble", "valeur": val})
        return {"valide": len(violations) == 0, "violations": violations, "n_lignes": len(lignes)}
