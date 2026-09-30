"""#606 — Backfill du funding REALISE, par coin. **X-04 a ete juge sur 18,9 h pour rien.**

═══════════════════════════════════════════════════════════════════════════════════════════════
LA MEME MALADIE, POUR LA DEUXIEME FOIS EN UNE JOURNEE
═══════════════════════════════════════════════════════════════════════════════════════════════

Ce matin : `candleSnapshot(coin, interval, **startTime**, endTime)` etait **deja ecrit**, **deja
autorise** -- on ne s'en servait que pour les bougies recentes. Resultat : 18,9 h d'historique de
prix, et **chaque** mesure qui mourait sur « data-limited ». -> 208 JOURS en un appel.

Ce soir, la meme chose sur le funding : `fundingHistory(coin, **startTime**)` est un endpoint
**PUBLIC**. Il donne des **MOIS** de funding realise, par coin.

    ***X-04 (120 paires, verdict « funding perp<->perp mort ») a ete mesure sur 18,9 h de
    funding enregistre en LIVE -- alors que l'historique etait public depuis toujours.***

    ***T2 / T2b (le carry HYPE, le SEUL resultat positif du projet) tient sur la meme fenetre.***

*Une capacite presente, un chainon manquant, personne qui se plaint.* La maladie du projet.

═══════════════════════════════════════════════════════════════════════════════════════════════

PRUDENCE (ce que je NE promets PAS) :
  * je ne sais pas encore quelle **profondeur** HL sert reellement sur `fundingHistory` --
    `candleSnapshot` plafonnait a ~5 000 points quel que soit le startTime. **On MESURE la
    couverture obtenue, on ne l'annonce pas d'avance.**
  * un verdict refait sur des mois peut **confirmer** X-04. C'est meme le plus probable.
    Refaire une mesure n'est pas esperer un resultat.

DENY-BY-DEFAULT : un enregistrement illisible est **JETE**, jamais devine.
PUR : aucun appel reseau ici. Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

MS_PAR_HEURE = 3_600_000

# HL paie le funding toutes les heures -> un enregistrement par heure et par coin.
INTERVALLE_FUNDING_MS = MS_PAR_HEURE

# On decoupe la demande en fenetres. Si HL plafonne (comme candleSnapshot a ~5 000 points),
# la pagination permet au moins de le CONSTATER, trou par trou.
HEURES_PAR_REQUETE = 500

MOTIF_ENREGISTREMENT_ILLISIBLE = "ENREGISTREMENT_DE_FUNDING_ILLISIBLE_JETE"


@dataclass(frozen=True, slots=True)
class PointFunding:
    coin: str
    time_ms: int
    funding: float          # taux HORAIRE (HL paie a l'heure) -- cf. funding_cross_venue
    premium: float | None = None

    @property
    def bps_h(self) -> float:
        return self.funding * 1e4

    def as_dict(self) -> dict[str, Any]:
        return {"coin": self.coin, "time": self.time_ms,
                "funding": self.funding, "premium": self.premium}


@dataclass(frozen=True, slots=True)
class CouvertureFunding:
    coin: str
    n_points: int
    debut_ms: int
    fin_ms: int
    n_trous: int
    heures_attendues: int

    @property
    def heures(self) -> float:
        return (self.fin_ms - self.debut_ms) / MS_PAR_HEURE

    @property
    def jours(self) -> float:
        return self.heures / 24.0

    def as_dict(self) -> dict[str, Any]:
        return {"coin": self.coin, "n_points": self.n_points,
                "debut_ms": self.debut_ms, "fin_ms": self.fin_ms,
                "heures": round(self.heures, 1), "jours": round(self.jours, 2),
                "n_trous": self.n_trous, "heures_attendues": self.heures_attendues}


def plan_de_requetes(
    *,
    debut_ms: int,
    fin_ms: int,
    heures_par_requete: int = HEURES_PAR_REQUETE,
) -> list[tuple[int, int]]:
    """Decoupe [debut, fin] en fenetres. Bornes strictes : on ne demande jamais le futur."""
    if debut_ms >= fin_ms:
        return []
    pas = max(1, int(heures_par_requete)) * MS_PAR_HEURE
    fenetres: list[tuple[int, int]] = []
    t = int(debut_ms)
    while t < fin_ms:
        fin = min(t + pas, int(fin_ms))
        fenetres.append((t, fin))
        t = fin
    return fenetres


def parser_funding(coin: str, payload: Any) -> list[PointFunding]:
    """Reponse de `fundingHistory` -> [PointFunding].

    Format HL : [{"coin":"BTC","fundingRate":"0.0000125","premium":"...","time":1733958000000}, ...]

    DENY-BY-DEFAULT : un enregistrement sans `time` ou sans `fundingRate` lisible est **JETE**.
    On n'invente ni un 0 (qui ferait croire a un funding nul) ni un timestamp.
    """
    out: list[PointFunding] = []
    if not isinstance(payload, list):
        return out
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        t = row.get("time")
        r = row.get("fundingRate")
        if t in (None, "") or r in (None, "", "null"):
            continue
        try:
            time_ms = int(t)
            taux = float(r)
        except (TypeError, ValueError):
            continue
        if time_ms <= 0:
            continue
        prem: float | None
        try:
            prem = float(row["premium"]) if row.get("premium") not in (None, "") else None
        except (TypeError, ValueError):
            prem = None
        # Le coin de la reponse fait foi s'il existe ; sinon celui qu'on a demande.
        nom = str(row.get("coin") or coin).strip().upper()
        out.append(PointFunding(coin=nom, time_ms=time_ms, funding=taux, premium=prem))
    return out


def dedupliquer(points: Iterable[PointFunding]) -> list[PointFunding]:
    """Les fenetres se chevauchent aux bornes : un meme (coin, time) ne doit PAS compter 2 fois.

    Un funding compte deux fois, c'est un carry qui rend le DOUBLE. Exactement le genre de
    faux edge que ce projet fabrique quand on ne regarde pas.
    """
    vus: dict[tuple[str, int], PointFunding] = {}
    for p in points:
        vus[(p.coin, p.time_ms)] = p
    return sorted(vus.values(), key=lambda p: (p.coin, p.time_ms))


def couverture(points: list[PointFunding], *, coin: str) -> CouvertureFunding | None:
    """Ce qu'on a REELLEMENT obtenu. `None` = etat vide honnete, jamais un chiffre invente."""
    pts = sorted((p for p in points if p.coin == coin.upper()), key=lambda p: p.time_ms)
    if len(pts) < 2:
        return None
    debut, fin = pts[0].time_ms, pts[-1].time_ms
    attendues = int(round((fin - debut) / INTERVALLE_FUNDING_MS)) + 1
    trous = 0
    for a, b in zip(pts, pts[1:]):
        ecart = b.time_ms - a.time_ms
        if ecart > INTERVALLE_FUNDING_MS * 1.5:
            trous += int(round(ecart / INTERVALLE_FUNDING_MS)) - 1
    return CouvertureFunding(coin=coin.upper(), n_points=len(pts), debut_ms=debut, fin_ms=fin,
                             n_trous=trous, heures_attendues=attendues)


def funding_cumule_bps(points: Iterable[PointFunding]) -> float:
    """Le funding TOTAL encaisse (short) sur la periode, en bps. Somme des taux horaires."""
    return sum(p.bps_h for p in points)


__all__ = [
    "HEURES_PAR_REQUETE", "INTERVALLE_FUNDING_MS", "MOTIF_ENREGISTREMENT_ILLISIBLE",
    "MS_PAR_HEURE", "CouvertureFunding", "PointFunding",
    "couverture", "dedupliquer", "funding_cumule_bps", "parser_funding", "plan_de_requetes",
]
