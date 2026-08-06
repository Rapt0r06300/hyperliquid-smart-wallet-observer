"""[Bloc 41-42 / AUD-068,070,100] Execution Cross-Venue : 2 jambes au MEME instant + gestion jambe
partielle / manquee / timeout / unwind + risque residuel.

Regle NON negociable : on ne laisse JAMAIS une jambe seule silencieusement. Si une jambe fill et l'autre
manque (ou timeout), on UNWIND la jambe filled et on expose le risque residuel. Une jambe partielle
laisse un residuel = portion non couverte. deterministe, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Optional


def executer_paire(leg_a: Mapping, leg_b: Mapping, *, fill_a: float, fill_b: float,
                   timeout_a: bool = False, timeout_b: bool = False) -> dict:
    """leg_x = {venue, symbole, side, notionnel}. fill_x = notionnel REELLEMENT execute (0..notionnel).
    Retourne l'etat: paired (couvert), unwound (jambe soldee), residual_risk_usd, raison."""
    na, nb = float(leg_a["notionnel"]), float(leg_b["notionnel"])
    fa = 0.0 if timeout_a else max(0.0, min(float(fill_a), na))
    fb = 0.0 if timeout_b else max(0.0, min(float(fill_b), nb))

    couvert = min(fa, fb)                 # portion appariee (les 2 jambes)
    excedent_a = fa - couvert             # jambe A remplie au-dela de l'appariement
    excedent_b = fb - couvert
    residual = excedent_a + excedent_b    # exposition non couverte (a unwind)

    raison = "apparie"
    unwound = 0.0
    if fa == 0.0 and fb == 0.0:
        raison = "aucune_jambe"
    elif fa == 0.0 or fb == 0.0:
        raison = "jambe_unique_unwind"    # une seule jambe -> on solde le residuel
        unwound = residual
    elif excedent_a > 1e-12 or excedent_b > 1e-12:
        raison = "jambe_partielle"

    return {"paired_usd": couvert, "residual_risk_usd": round(residual, 6), "unwound_usd": round(unwound, 6),
            "raison": raison, "fill_a": fa, "fill_b": fb,
            "expose_une_jambe": (fa == 0.0) != (fb == 0.0)}


class CrossVenueExecutor:
    """Suit les paires en cours et agrege le risque residuel total (jamais masque)."""

    def __init__(self) -> None:
        self.paires = []

    def soumettre(self, leg_a: Mapping, leg_b: Mapping, *, fill_a: float, fill_b: float,
                  timeout_a: bool = False, timeout_b: bool = False) -> dict:
        etat = executer_paire(leg_a, leg_b, fill_a=fill_a, fill_b=fill_b,
                              timeout_a=timeout_a, timeout_b=timeout_b)
        self.paires.append(etat)
        return etat

    def risque_residuel_total(self) -> float:
        return round(sum(p["residual_risk_usd"] for p in self.paires), 6)

    def jambes_uniques(self) -> int:
        return sum(1 for p in self.paires if p["expose_une_jambe"])
