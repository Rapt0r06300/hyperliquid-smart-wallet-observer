"""ALPHA-7 — toxicité et crowding des métaordres (SHADOW, pur, 0 réseau, 0 ordre).

But unique : **ne pas être le dernier copieur du mouvement.** Le papier Hyperliquid 2026 suggère qu'un flux
caché dans le même sens qu'un TWAP visible peut supporter davantage d'impact permanent ; ce n'est pas une
preuve de profit, c'est une raison de mesurer le risque d'arriver tard.

Ce module ne redétecte pas les métaordres — `metaorder_shadow` le fait déjà (`detecter_metaordres`,
`classer_stade`). Il ajoute quatre mesures de toxicité et une porte :

1. **Crowding** : combien de métaordres du MÊME sens sont actifs en même temps sur le même coin.
2. **Imbalance extrême** : déséquilibre statique du top-5 normalisé par la profondeur.
3. **Profondeur qui se reconstruit alors que le prix est DÉJÀ parti** — le carnet a l'air sain, mais le
   mouvement est derrière nous : c'est la signature du copieur en retard.
4. **Markout adverse après slice** : ce que le prix fait CONTRE nous après la tranche.

Deny-by-default : toute entrée manquante donne `None`, jamais `False` ni `0.0`. La porte ne peut
qu'ABSTENIR ou refuser — elle ne crée jamais une entrée. Verdict `shadow=True`, `promotion_possible=False` :
elle ne deviendra contraignante que si une ablation OOS le prouve, décidée ailleurs.
"""
from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.experimental.metaorder_l2_tape import book_imbalance_top5, profondeur_top5

VERSION = "metaorder_toxicite_v1"

#: Stades produits par `metaorder_shadow.classer_stade`. Un test prouve que cette liste reste synchronisée.
STADES = ("FIRST_SLICE", "CONTINUATION", "LATE_STAGE", "REVERSAL")
STADES_TARDIFS = ("LATE_STAGE", "REVERSAL")

#: Seuils PRÉ-ENREGISTRÉS (fixés avant lecture des données).
SEUILS: dict[str, float] = {
    "crowding_fenetre_ms": 60_000.0,
    "crowding_min_concurrents": 2.0,     # >= 2 métaordres même sens simultanés = encombré
    "imbalance_extreme_ratio": 0.60,     # |bid-ask| / profondeur top-5
    "prix_deja_parti_bps": 15.0,
    "markout_adverse_bps": -5.0,
    "ablation_min_episodes": 30.0,
}


# ════════════════════════════ 1. crowding ════════════════════════════
def metaordres_concurrents(metaordres: Iterable[Mapping[str, Any]], *, t_ms: float, sens: int,
                           fenetre_ms: float | None = None) -> dict[str, Any]:
    """Métaordres actifs à `t_ms` (fenêtre de tolérance après `t1`), séparés par sens.

    `sens` doit valoir +1 ou -1 ; sinon la mesure est déclarée non mesurable plutôt que devinée.
    """
    if sens not in (1, -1):
        return {"meme_sens": None, "sens_oppose": None, "encombre": None, "raison": "SENS_INCONNU"}
    fen = float(SEUILS["crowding_fenetre_ms"] if fenetre_ms is None else fenetre_ms)
    meme = oppose = 0
    for m in metaordres:
        try:
            t0, t1, s = float(m["t0"]), float(m["t1"]), int(m["sens"])
        except (KeyError, TypeError, ValueError):
            continue
        if t0 <= float(t_ms) <= t1 + fen:
            if s == sens:
                meme += 1
            elif s == -sens:
                oppose += 1
    return {"meme_sens": meme, "sens_oppose": oppose,
            "encombre": bool(meme >= SEUILS["crowding_min_concurrents"]), "raison": None}


# ════════════════════════════ 2. imbalance extrême ════════════════════════════
def imbalance_extreme(resume: Mapping[str, Any] | None, *, seuil: float | None = None) -> dict[str, Any]:
    """Déséquilibre du top-5 normalisé par la profondeur. `None` si le carnet est illisible."""
    desequilibre = book_imbalance_top5(resume)
    profondeur = profondeur_top5(resume)
    if desequilibre is None or not profondeur:
        return {"ratio": None, "extreme": None, "raison": "CARNET_NON_MESURABLE"}
    ratio = desequilibre / profondeur
    limite = float(SEUILS["imbalance_extreme_ratio"] if seuil is None else seuil)
    return {"ratio": round(ratio, 6), "extreme": bool(abs(ratio) >= limite), "raison": None}


# ════════════════════════════ 3. profondeur reconstruite, prix déjà parti ════════════════════════════
def profondeur_reconstruite_prix_parti(*, resume_avant: Mapping[str, Any] | None,
                                       resume_apres: Mapping[str, Any] | None,
                                       mid_avant: float | None, mid_apres: float | None, sens: int,
                                       seuil_bps: float | None = None) -> dict[str, Any]:
    """Le carnet se réépaissit ALORS QUE le prix a déjà bougé dans le sens du métaordre : on arrive tard."""
    avant = profondeur_top5(resume_avant)
    apres = profondeur_top5(resume_apres)
    if avant is None or apres is None or sens not in (1, -1):
        return {"profondeur_en_hausse": None, "deplacement_bps": None, "prix_deja_parti": None,
                "en_retard": None, "raison": "DONNEES_INSUFFISANTES"}
    if not isinstance(mid_avant, (int, float)) or not isinstance(mid_apres, (int, float)) or mid_avant <= 0:
        return {"profondeur_en_hausse": bool(apres > avant), "deplacement_bps": None,
                "prix_deja_parti": None, "en_retard": None, "raison": "MID_NON_MESURABLE"}
    deplacement = sens * (float(mid_apres) - float(mid_avant)) / float(mid_avant) * 1e4
    limite = float(SEUILS["prix_deja_parti_bps"] if seuil_bps is None else seuil_bps)
    hausse = bool(apres > avant)
    parti = bool(deplacement >= limite)
    return {"profondeur_en_hausse": hausse, "deplacement_bps": round(deplacement, 4),
            "prix_deja_parti": parti, "en_retard": bool(hausse and parti), "raison": None}


# ════════════════════════════ 4. markout adverse ════════════════════════════
def markout_adverse_bps(prix_slice: float | None, prix_forward: float | None, sens: int) -> float | None:
    """Markout SIGNÉ après la tranche : négatif = le prix va contre le copieur. `None` si non mesurable."""
    if sens not in (1, -1):
        return None
    try:
        pe = float(prix_slice)
        pf = float(prix_forward)
    except (TypeError, ValueError):
        return None
    if pe <= 0:
        return None
    return round(sens * (pf - pe) / pe * 1e4, 4)


# ════════════════════════════ porte SHADOW ════════════════════════════
def gate_toxicite(*, stade: str | None = None, crowding: Mapping[str, Any] | None = None,
                  imbalance: Mapping[str, Any] | None = None, retard: Mapping[str, Any] | None = None,
                  markout_bps: float | None = None) -> dict[str, Any]:
    """Porte `LATE_OR_CROWDED_NO_TRADE`, en SHADOW. Ne peut que refuser ou s'abstenir, jamais autoriser une
    entrée que le moteur n'aurait pas déjà décidée."""
    motifs: list[str] = []
    non_mesurables: list[str] = []

    if stade is None:
        non_mesurables.append("STADE")
    elif stade in STADES_TARDIFS:
        motifs.append("STADE_%s" % stade)

    if crowding is None or crowding.get("encombre") is None:
        non_mesurables.append("CROWDING")
    elif crowding.get("encombre"):
        motifs.append("CROWDING_%s_METAORDRES_MEME_SENS" % crowding.get("meme_sens"))

    if imbalance is None or imbalance.get("extreme") is None:
        non_mesurables.append("IMBALANCE")
    elif imbalance.get("extreme"):
        motifs.append("IMBALANCE_EXTREME")

    if retard is None or retard.get("en_retard") is None:
        non_mesurables.append("PROFONDEUR_PRIX")
    elif retard.get("en_retard"):
        motifs.append("PROFONDEUR_RECONSTRUITE_PRIX_DEJA_PARTI")

    if markout_bps is None:
        non_mesurables.append("MARKOUT")
    elif markout_bps <= SEUILS["markout_adverse_bps"]:
        motifs.append("MARKOUT_ADVERSE")

    if motifs:
        verdict = "LATE_OR_CROWDED_NO_TRADE"
    elif non_mesurables:
        verdict = "ABSTAIN_UNMEASURABLE"
    else:
        verdict = "ALLOW_SHADOW"
    return {"verdict": verdict, "motifs": motifs, "non_mesurables": non_mesurables,
            "version": VERSION, "shadow": True, "promotion_possible": False, "real_execution": False}


# ════════════════════════════ ablation (mesure, pas promotion) ════════════════════════════
def ablation_gate(episodes: Sequence[Mapping[str, Any]], *, min_episodes: int | None = None) -> dict[str, Any]:
    """Compare le net moyen AVEC et SANS la porte sur les mêmes épisodes.

    Chaque épisode porte `net_bps` et `verdict`. Un échantillon insuffisant rend `AMELIORATION_NON_MESURABLE` —
    jamais une amélioration proclamée. Ce module ne promeut rien : `promotion_possible=False`.
    """
    seuil = int(SEUILS["ablation_min_episodes"] if min_episodes is None else min_episodes)
    tous = [float(e["net_bps"]) for e in episodes if isinstance(e.get("net_bps"), (int, float))]
    gardes = [float(e["net_bps"]) for e in episodes
              if isinstance(e.get("net_bps"), (int, float)) and e.get("verdict") != "LATE_OR_CROWDED_NO_TRADE"]
    base: dict[str, Any] = {"n_total": len(tous), "n_apres_gate": len(gardes),
                            "n_refuses": len(tous) - len(gardes), "min_episodes": seuil,
                            "shadow": True, "promotion_possible": False}
    if len(tous) < seuil or len(gardes) < 2:
        return {**base, "statut": "AMELIORATION_NON_MESURABLE", "net_moyen_sans_gate": None,
                "net_moyen_avec_gate": None, "delta_bps": None,
                "raison": "%d episodes < %d requis" % (len(tous), seuil)}
    sans = statistics.mean(tous)
    avec = statistics.mean(gardes)
    delta = avec - sans
    return {**base, "statut": "MESURE", "net_moyen_sans_gate": round(sans, 4),
            "net_moyen_avec_gate": round(avec, 4), "delta_bps": round(delta, 4),
            "gate_utile": bool(delta > 0),
            "note": "un delta positif reste une MESURE en shadow, pas une promotion"}


__all__ = [
    "VERSION", "STADES", "STADES_TARDIFS", "SEUILS", "metaordres_concurrents", "imbalance_extreme",
    "profondeur_reconstruite_prix_parti", "markout_adverse_bps", "gate_toxicite", "ablation_gate",
]
