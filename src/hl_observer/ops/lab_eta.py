"""[LAB α] MOTEUR ETA : estimation honnête de l'avancement. Tant qu'il n'y a pas assez de mesures, on affiche
`ETA EN CALIBRATION` (jamais un faux ETA précis). Ensuite, l'ETA est recalculé à partir de la durée réelle des
étapes déjà terminées, du travail restant et de la variance observée (bande de confiance). Pur/déterministe :
le temps courant est fourni par l'appelant (aucun accès horloge dans le module → testable). 0 réseau, 0 ordre.
"""
from __future__ import annotations

import math
from typing import Any


def format_hms(secondes: Any) -> str:
    try:
        s = int(max(0.0, float(secondes)))
    except (TypeError, ValueError):
        return "--:--:--"
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


class MoteurETA:
    """Suit les durées réelles des étapes et estime le reste. min_echantillons avant de sortir de calibration."""

    def __init__(self, *, total_etapes: int, total_octets: int = 0, min_echantillons: int = 3) -> None:
        self.total_etapes = max(1, int(total_etapes))
        self.total_octets = int(total_octets)
        self.min = max(1, int(min_echantillons))
        self._durees: list[float] = []
        self.etapes_finies = 0
        self.octets_traites = 0
        self.evenements_traites = 0

    def terminer_etape(self, duree_s: float, *, octets: int = 0, evenements: int = 0) -> None:
        self._durees.append(max(0.0, float(duree_s)))
        self.etapes_finies += 1
        self.octets_traites += int(octets)
        self.evenements_traites += int(evenements)

    def _debits(self, elapsed_s: float) -> dict[str, Any]:
        """Débit RÉEL observé (item 15) : événements/s et octets/s depuis le début. elapsed<=0 → None."""
        el = float(elapsed_s)
        if el <= 0:
            return {"debit_evenements_s": None, "debit_octets_s": None}
        return {"debit_evenements_s": round(self.evenements_traites / el, 3),
                "debit_octets_s": round(self.octets_traites / el, 1)}

    def progres(self) -> dict[str, Any]:
        pct = round(100.0 * self.etapes_finies / self.total_etapes, 2)
        return {"etapes_finies": self.etapes_finies, "total_etapes": self.total_etapes,
                "octets_traites": self.octets_traites, "total_octets": self.total_octets,
                "evenements_traites": self.evenements_traites, "pct": pct,
                # durée PROPRE de chaque étape (item 15) : dernière + moyenne, pas un cumul trompeur.
                "derniere_duree_s": round(self._durees[-1], 3) if self._durees else None,
                "duree_moyenne_s": round(sum(self._durees) / len(self._durees), 3) if self._durees else None}

    def estimer(self, *, elapsed_s: float) -> dict[str, Any]:
        """Retourne l'estimation courante. Calibration tant que < min_echantillons étapes terminées.
        Expose le débit réel, la durée propre de la dernière étape, l'heure de fin (offset) et
        l'intervalle d'incertitude [eta_bas, eta_haut]."""
        base = {**self.progres(), **self._debits(elapsed_s)}
        if self.etapes_finies < self.min:
            return {**base, "calibration": True, "eta_total_s": None, "fin_relative_s": None,
                    "confiance_s": None, "eta_bas_s": None, "eta_haut_s": None, "texte": "ETA EN CALIBRATION"}
        moy = sum(self._durees) / len(self._durees)
        reste = max(0, self.total_etapes - self.etapes_finies)
        eta = moy * reste
        if len(self._durees) >= 2:
            m = sum(self._durees) / len(self._durees)
            std = math.sqrt(sum((x - m) ** 2 for x in self._durees) / (len(self._durees) - 1))
        else:
            std = 0.0
        band = 1.645 * std * math.sqrt(max(1, reste))
        texte = "ETA %s — confiance +/- %d min" % (format_hms(eta), round(band / 60.0))
        return {**base, "calibration": False, "eta_total_s": round(eta, 3),
                "fin_relative_s": round(float(elapsed_s) + eta, 3), "confiance_s": round(band, 3),
                # intervalle d'incertitude explicite (item 15) : bornes basse/haute de l'ETA.
                "eta_bas_s": round(max(0.0, eta - band), 3), "eta_haut_s": round(eta + band, 3),
                "texte": texte}


__all__ = ["MoteurETA", "format_hms"]
