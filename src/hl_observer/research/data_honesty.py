"""[AUD-350/384/386/387/388] Gardes ANTI-MENSONGE de donnees : interdire SUCCESS si zero donnee,
interdire les zeros INVENTES (vrai 0 mesure vs non-mesure=None), detecter le carry-forward
SILENCIEUX, rejeter les donnees REVISEES non point-in-time, et QUARANTAINER les champs inconnus.
Deny-by-default. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def interdire_success_si_zero_donnee(statut: str, n_evenements: int) -> dict:
    """Un collecteur ne peut PAS retourner SUCCESS avec 0 evenement utile (faux vert classique)."""
    ment = str(statut).upper() in ("SUCCESS", "OK", "PASSED") and n_evenements <= 0
    return {"honnete": not ment, "statut_corrige": "NO_DATA" if ment else statut,
            "n_evenements": n_evenements}


def distinguer_zero(valeur: Any, *, mesuree: bool) -> dict:
    """Un 0 MESURE est un fait ; un 0 par defaut (non mesure) est un mensonge. On renvoie None/
    UNMEASURED quand la valeur n'a pas ete mesuree, jamais un faux 0."""
    if not mesuree:
        return {"valeur": None, "etat": "UNMEASURED"}
    return {"valeur": valeur, "etat": "MESURE"}


def detecter_carry_forward_silencieux(serie: Sequence[Mapping]) -> dict:
    """Carry-forward SILENCIEUX : meme valeur repetee SANS nouvel horodatage de source (le panneau
    montre un chiffre 'frais' qui ne bouge plus depuis des heures)."""
    suspects = [i for i in range(1, len(serie))
                if serie[i - 1].get("valeur") == serie[i].get("valeur")
                and serie[i - 1].get("source_ts") == serie[i].get("source_ts")]
    return {"carry_forward": len(suspects) > 0, "indices": suspects}


def rejeter_donnees_revisees_non_pit(enregistrements: Sequence[Mapping]) -> dict:
    """Rejette toute donnee REVISEE sans asof point-in-time : une revision sans asof injecte du futur
    dans le passe (look-ahead)."""
    rejetes = [i for i, e in enumerate(enregistrements) if e.get("revised") and e.get("asof") is None]
    return {"ok": len(rejetes) == 0, "rejetes": rejetes}


def quarantaine_champs_inconnus(ligne: Mapping, champs_connus: Sequence[str]) -> dict:
    """Quarantaine les champs INCONNUS d'une ligne (schema drift) au lieu de les ignorer en silence."""
    connus = set(champs_connus)
    inconnus = sorted(k for k in ligne if k not in connus)
    propre = {k: v for k, v in ligne.items() if k in connus}
    return {"propre": propre, "quarantaine": inconnus, "a_des_inconnus": len(inconnus) > 0}
