"""K3 — CALIBRATION DES PROBABILITÉS : un score « 70% » doit gagner ~70% du temps.

Une proba mal calibrée casse le sizing Kelly (E22) et le edge net (on parie trop/pas assez). On
mesure l'ERREUR DE CALIBRATION (ECE) : par bin de proba prédite, l'écart |proba moyenne − fréquence
réelle|, pondéré. Bas = bien calibré. PUR. Deny-by-default : pas de données -> None. PAPER only.
"""
from __future__ import annotations

from typing import Sequence

SEUIL_ECE = 0.1        # ECE > 0.1 = mal calibre (a recalibrer avant de sizer dessus)


def courbe_fiabilite(probas: Sequence[float], resultats: Sequence[int], *, n_bins: int = 10):
    """Renvoie [(centre_bin, proba_moyenne, freq_reelle, n)] pour les bins non vides."""
    bins: list[list] = [[] for _ in range(int(n_bins))]
    for p, r in zip(probas or [], resultats or []):
        idx = min(int(n_bins) - 1, max(0, int(float(p) * n_bins)))
        bins[idx].append((float(p), int(bool(r))))
    out = []
    for i, b in enumerate(bins):
        if b:
            pm = sum(p for p, _ in b) / len(b)
            fr = sum(r for _, r in b) / len(b)
            out.append(((i + 0.5) / n_bins, round(pm, 4), round(fr, 4), len(b)))
    return out


def erreur_calibration(probas: Sequence[float], resultats: Sequence[int], *, n_bins: int = 10) -> float | None:
    """ECE = somme pondérée par bin de |proba_moyenne − fréquence_réelle|. None si pas de données."""
    n_total = min(len(probas or []), len(resultats or []))
    if n_total == 0:
        return None
    ece = 0.0
    for _c, pm, fr, n in courbe_fiabilite(probas, resultats, n_bins=n_bins):
        ece += (n / n_total) * abs(pm - fr)
    return round(ece, 6)


def est_calibre(probas: Sequence[float], resultats: Sequence[int], *, seuil_ece: float = SEUIL_ECE,
                n_bins: int = 10) -> bool:
    """True si l'ECE est sous le seuil. Non mesurable -> False (deny-by-default)."""
    ece = erreur_calibration(probas, resultats, n_bins=n_bins)
    return ece is not None and ece <= float(seuil_ece)


__all__ = ["SEUIL_ECE", "courbe_fiabilite", "erreur_calibration", "est_calibre"]
