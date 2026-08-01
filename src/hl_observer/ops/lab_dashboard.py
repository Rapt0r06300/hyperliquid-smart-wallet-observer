"""[LAB α] TABLEAU DE BORD dynamique + JOURNAL horodaté. Une zone claire (pas des milliers de lignes qui
défilent) qui montre l'action exacte en cours, l'ETA, les débits et les meilleurs PnL ; en parallèle un journal
horodaté qui enregistre chaque changement significatif. Le rendu est pur (chaîne) → testable ; l'appelant décide
d'imprimer/rafraîchir. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _g(etat: dict[str, Any], cle: str, defaut: Any = "-") -> Any:
    v = etat.get(cle)
    return defaut if v is None else v


def rendre_tableau(etat: dict[str, Any]) -> str:
    """Rend la zone dynamique. `etat` porte tous les champs de suivi (heure, ETA, étape, fichier, débits, PnL...)."""
    b = "=" * 78
    lignes = [
        b,
        "  LABORATOIRE ALPHA — %s" % _g(etat, "titre", "run"),
        "  HEURE %s | ECOULE %s | ETA %s | ETA_ETAPE %s" % (
            _g(etat, "heure"), _g(etat, "ecoule"), _g(etat, "eta"), _g(etat, "eta_etape")),
        "  FIN ESTIMEE %s | CONFIANCE %s" % (_g(etat, "fin_estimee"), _g(etat, "confiance")),
        "-" * 78,
        "  ETAPE %s / %s   SOUS-ETAPE %s" % (_g(etat, "etape"), _g(etat, "total_etapes"), _g(etat, "sous_etape")),
        "  FICHIER %s" % _g(etat, "fichier"),
        "  SOURCE %s | CANAL %s | PERIODE %s" % (_g(etat, "source"), _g(etat, "canal"), _g(etat, "periode")),
        "  OCTETS %s / %s | EVENTS lus %s valides %s rejetes %s" % (
            _g(etat, "octets_lus"), _g(etat, "octets_total"), _g(etat, "events_lus"),
            _g(etat, "events_valides"), _g(etat, "events_rejetes")),
        "  DEBIT %s evt/s | %s Mo/s" % (_g(etat, "evt_s"), _g(etat, "mo_s")),
        "  CONFIGS prevues %s testees %s eliminees %s restantes %s" % (
            _g(etat, "cfg_prevues"), _g(etat, "cfg_testees"), _g(etat, "cfg_eliminees"), _g(etat, "cfg_restantes")),
        "  REPLAYS %s | FILLS %s | MISSED %s" % (_g(etat, "replays"), _g(etat, "fills"), _g(etat, "missed")),
        "  meilleur PnL  IS %s | OOS %s | FORWARD %s | ADVERSE_P95 %s | DD %s" % (
            _g(etat, "best_is"), _g(etat, "best_oos"), _g(etat, "best_fwd"),
            _g(etat, "best_adv95"), _g(etat, "best_dd")),
        "  ERREURS %s | ALERTES %s | MANQUANTES %s | MEM %s | WORKERS %s" % (
            _g(etat, "erreurs"), _g(etat, "alertes"), _g(etat, "manquantes"),
            _g(etat, "mem"), _g(etat, "workers")),
        "-" * 78,
        "  DERNIERE   %s" % _g(etat, "derniere"),
        "  EN COURS   %s" % _g(etat, "en_cours"),
        "  PROCHAINE  %s" % _g(etat, "prochaine"),
        b,
    ]
    return "\n".join(lignes)


class Journal:
    """Journal horodaté append-only : enregistre chaque changement significatif (une ligne par événement)."""

    def __init__(self, chemin: str | Path) -> None:
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.lignes: list[str] = []

    def ligne(self, horodatage: str, message: str) -> None:
        entree = "%s | %s" % (horodatage, message)
        self.lignes.append(entree)
        try:
            with open(self.chemin, "a", encoding="utf-8") as fh:
                fh.write(entree + "\n")
        except OSError:
            pass


__all__ = ["rendre_tableau", "Journal"]
