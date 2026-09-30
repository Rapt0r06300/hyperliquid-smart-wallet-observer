"""C12 + C13 — SÉLECTION & FILTRE des leaders par MARKOUT FORWARD réel.

LA CAUSE mesurée de l'échec du copy (−7,97 bps OOS) : le leader moyen est **contrarien** — le prix
bouge CONTRE lui après son fill. Le problème est le CONTENU, pas la vitesse. La réponse honnête :
ne copier QUE les leaders dont les fills PRÉDISENT, c.-à-d. dont le markout forward est POSITIF.

markout d'un fill (bps, sur le MID — JAMAIS un prix de trade, sinon le bid-ask bounce fabrique un
edge) = (mid[t+h] − mid[t]) / mid[t] × (+1 si le leader ACHÈTE, −1 s'il VEND). Positif = sa
direction était bonne.

  * C12 (sélection)  : garder les leaders au markout moyen > seuil (deny-by-default : < N events → out).
  * C13 (filtre live): ne copier un signal QUE si le markout RÉCENT du leader est encore positif.

Module PUR. Un score n'est pas un ordre ; le noyau garde l'autorité (frais, VPIN, edge net). PAPER only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

MIN_EVENEMENTS = 20        # < 20 fills : pas de verdict (un chiffre sur 3 fills ment). Cf. doctrine markout.
MIN_MARKOUT_BPS = 0.0      # au minimum le leader doit PRÉDIRE (markout > 0) ; l'edge net après coûts = noyau

#: 🔴 22/07 — LE COÛT DE SUIVRE UN LEADER. Copier, c'est arriver APRÈS lui : on est TAKER a
#: l'entree ET a la sortie (on n'a pas le luxe d'attendre un fill maker, le prix bouge deja
#: dans son sens). Taker HL tier 0 = 4,5 bps -> aller-retour = 9,0 bps. Un leader dont le
#: markout brut ne depasse pas 9 bps nous fait PERDRE quand on le suit, meme s'il « predit ».
#: C'est le meme piege que le forfait d'arbitrage : un markout brut n'est pas un edge net.
#: (La degradation de copie — latence, prix deja parti — s'AJOUTE a ce cout ; elle est mesuree
#: a part par le noyau. 9 bps est donc un PLANCHER de cout, pas le cout complet.)
COPY_FOLLOW_COST_BPS = 9.0


def markout_net_de_copie_bps(markout_brut_bps: float | None,
                             cout_suivi_bps: float = COPY_FOLLOW_COST_BPS) -> float | None:
    """Le markout NET, une fois payé le coût de suivre le leader (taker aller-retour).

    C'est LUI qui dit si copier ce leader gagne de l'argent, pas le brut. `None` reste `None` :
    on ne fabrique pas un edge pour un leader qu'on n'a pas su mesurer.
    """
    if markout_brut_bps is None:
        return None
    return round(float(markout_brut_bps) - float(cout_suivi_bps), 4)


def markout_fill_bps(side: str, mid_at_fill: float, mid_forward: float) -> float | None:
    """Markout forward d'UN fill, sur le MID. None si prix invalide."""
    try:
        m0 = float(mid_at_fill)
        if m0 <= 0:
            return None
        r = (float(mid_forward) - m0) / m0 * 10_000.0
    except (TypeError, ValueError):
        return None
    s = str(side or "").upper()
    if s in ("BUY", "LONG", "B"):
        return r
    if s in ("SELL", "SHORT", "S", "A"):
        return -r
    return None


def markout_leader_bps(fills: Iterable[dict], *, cle_forward: str = "mid_forward") -> tuple[float | None, int]:
    """(markout moyen bps, n) sur les fills d'un leader. Chaque fill : {side, mid_at_fill, <cle_forward>}."""
    ms: list[float] = []
    for f in fills or []:
        if not isinstance(f, dict):
            continue
        m = markout_fill_bps(f.get("side"), f.get("mid_at_fill"), f.get(cle_forward))
        if m is not None:
            ms.append(m)
    if not ms:
        return None, 0
    return sum(ms) / len(ms), len(ms)


@dataclass(frozen=True, slots=True)
class VerdictLeader:
    adresse: str
    n_evenements: int
    markout_moyen_bps: float | None
    predit: bool
    motif: str


def juger_leader(adresse: str, fills: Iterable[dict], *, min_events: int = MIN_EVENEMENTS,
                 min_markout_bps: float = MIN_MARKOUT_BPS, cle_forward: str = "mid_forward") -> VerdictLeader:
    """C12 : un leader est GARDÉ seulement s'il a assez d'events ET un markout forward > seuil.
    Deny-by-default : historique trop court -> non gardé (on ne devine pas)."""
    moy, n = markout_leader_bps(fills, cle_forward=cle_forward)
    if n < int(min_events) or moy is None:
        return VerdictLeader(str(adresse), n, moy, False, "TROP_PEU_D_EVENEMENTS")
    if moy <= float(min_markout_bps):
        return VerdictLeader(str(adresse), n, round(moy, 4), False, "LEADER_CONTRARIEN_OU_NEUTRE")
    return VerdictLeader(str(adresse), n, round(moy, 4), True, "LEADER_PREDIT")


def selectionner_leaders(par_leader: dict[str, Iterable[dict]], **kw) -> list[VerdictLeader]:
    """C12 : renvoie les verdicts, les PRÉDICTEURS d'abord (markout décroissant)."""
    verdicts = [juger_leader(a, f, **kw) for a, f in (par_leader or {}).items()]
    return sorted(verdicts, key=lambda v: (not v.predit, -(v.markout_moyen_bps or -9e9)))


def copier_ce_leader(fills_recents: Iterable[dict], *, min_events: int = MIN_EVENEMENTS,
                     min_markout_bps: float = MIN_MARKOUT_BPS, cle_forward: str = "mid_forward") -> bool:
    """C13 : filtre LIVE — ne copier le signal courant que si le markout RÉCENT du leader est > seuil."""
    return juger_leader("", fills_recents, min_events=min_events, min_markout_bps=min_markout_bps,
                        cle_forward=cle_forward).predit


__all__ = ["MIN_EVENEMENTS", "MIN_MARKOUT_BPS", "markout_fill_bps", "markout_leader_bps",
           "VerdictLeader", "juger_leader", "selectionner_leaders", "copier_ce_leader"]
