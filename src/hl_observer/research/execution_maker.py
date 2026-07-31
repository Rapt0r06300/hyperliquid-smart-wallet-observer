"""ALPHA — modèles d'EXÉCUTION : coût taker exécutable + maker QUEUE-AWARE RÉEL (fin de la sensibilité fictive).

Le run précédent chiffrait le maker par un simple « −3 bps de frais » : c'est une hypothèse de fill, pas un
modèle. Ici on modélise honnêtement l'exécution maker :

  * **position de file d'attente** : on se poste DERRIÈRE la taille déjà présente au niveau (`taille_devant`) ;
  * **probabilité de fill** : on n'est rempli que si le **volume agressif traversant** pendant qu'on est posté
    consomme `taille_devant + notre_taille`. Ce volume vient des **trades** — donnée qu'on n'a PAS ici pour ces
    coins → la proba de fill sort en `UNMEASURABLE` (jamais supposée = 1) ;
  * **sélection adverse** : on est rempli préférentiellement quand le marché tourne contre nous ; sans les
    trades signés, ce terme est aussi `UNMEASURABLE`.

Conséquence honnête : le maker queue-aware n'est PAS mesurable sans un tape de trades — le module fournit
l'interface complète et branche le flux dès qu'il existe, mais refuse d'inventer un net maker. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
TAKER = "TAKER"
MAKER = "MAKER"

FRAIS_TAKER_ROUNDTRIP_BPS = 9.0
FRAIS_MAKER_ROUNDTRIP_BPS = 3.0


def cout_taker_bps(spread_bps: float, *, fees_bps: float = FRAIS_TAKER_ROUNDTRIP_BPS) -> float:
    """Coût taker aller-retour exécutable : on paie le spread (crossing) + les frais taker."""
    return float(fees_bps) + max(0.0, float(spread_bps))


def position_file_attente(taille_devant: float, notre_taille: float = 1.0) -> float | None:
    """Fraction de la file à consommer avant NOTRE fill = taille_devant / (taille_devant + notre_taille)."""
    d = float(taille_devant) + float(notre_taille)
    if d <= 0:
        return None
    return float(taille_devant) / d


def proba_fill_maker(taille_devant: float | None, volume_traversant: float | None,
                     notre_taille: float = 1.0) -> float | None:
    """P(fill) sur l'horizon de post. `None` (UNMEASURABLE) si le volume traversant (trades) est absent."""
    if taille_devant is None or volume_traversant is None:
        return None
    besoin = float(taille_devant) + float(notre_taille)
    if besoin <= 0:
        return 0.0
    return max(0.0, min(1.0, float(volume_traversant) / besoin))


def net_maker_si_fill_bps(edge_signal_bps: float, *, spread_capture_bps: float,
                          adverse_selection_bps: float, fees_maker_bps: float = FRAIS_MAKER_ROUNDTRIP_BPS) -> float:
    """PnL maker CONDITIONNEL au fill = capture spread + edge signal − sélection adverse − frais maker."""
    return float(spread_capture_bps) + float(edge_signal_bps) - float(adverse_selection_bps) - float(fees_maker_bps)


def evaluer_execution(edge_signal_bps: float, *, mode: str, spread_bps: float,
                      taille_devant: float | None = None, volume_traversant: float | None = None,
                      notre_taille: float = 1.0, adverse_selection_bps: float | None = None,
                      fees_taker_bps: float = FRAIS_TAKER_ROUNDTRIP_BPS,
                      fees_maker_bps: float = FRAIS_MAKER_ROUNDTRIP_BPS) -> dict[str, Any]:
    """Net d'un edge-signal selon le mode d'exécution. TAKER = mesurable ; MAKER = mesurable UNIQUEMENT si
    volume traversant ET sélection adverse fournis (sinon UNMEASURABLE, jamais inventé)."""
    if mode == TAKER:
        return {"mode": TAKER, "statut": "MEASURABLE",
                "net_bps": round(float(edge_signal_bps) - cout_taker_bps(spread_bps, fees_bps=fees_taker_bps), 4),
                "proba_fill": 1.0}
    if mode == MAKER:
        p = proba_fill_maker(taille_devant, volume_traversant, notre_taille)
        if p is None or adverse_selection_bps is None:
            return {"mode": MAKER, "statut": "UNMEASURABLE", "net_bps": UNMEASURABLE, "proba_fill": p,
                    "manque": "volume traversant (trades signés) + sélection adverse — absent des données"}
        net_fill = net_maker_si_fill_bps(edge_signal_bps, spread_capture_bps=float(spread_bps) / 2.0,
                                         adverse_selection_bps=adverse_selection_bps, fees_maker_bps=fees_maker_bps)
        return {"mode": MAKER, "statut": "MEASURABLE", "net_bps": round(p * net_fill, 4),
                "proba_fill": round(p, 4), "net_si_fill_bps": round(net_fill, 4)}
    raise ValueError("mode inconnu: %r" % mode)


#: Matrice d'exécution demandée : (entrée, sortie). MAKER/MAKER seulement si preuve de queue (volume traversant).
MATRICE_EXECUTION = (
    ("TAKER", "TAKER"),
    ("MAKER", "TAKER"),
    ("TAKER", "MAKER"),
    ("MAKER", "MAKER"),   # seulement si volume traversant fourni aux DEUX jambes
)


def evaluer_matrice(edge_signal_bps: float, *, spread_bps: float, taille_devant: float | None = None,
                    volume_traversant: float | None = None, adverse_selection_bps: float | None = None) -> dict[str, Any]:
    """Évalue les 4 combinaisons entrée/sortie. Les jambes MAKER restent UNMEASURABLE sans volume+adverse."""
    out: dict[str, Any] = {}
    for entree, sortie in MATRICE_EXECUTION:
        # coût = jambe d'entrée + jambe de sortie ; on répartit l'edge et les frais par jambe.
        legs = []
        ok = True
        for role in (entree, sortie):
            r = evaluer_execution(edge_signal_bps / 2.0, mode=role, spread_bps=spread_bps / 2.0,
                                  taille_devant=taille_devant, volume_traversant=volume_traversant,
                                  adverse_selection_bps=(adverse_selection_bps / 2.0 if adverse_selection_bps is not None else None))
            legs.append(r)
            ok = ok and r["statut"] == "MEASURABLE"
        out["%s/%s" % (entree, sortie)] = {
            "statut": "MEASURABLE" if ok else "UNMEASURABLE",
            "net_bps": round(sum(l["net_bps"] for l in legs), 4) if ok else UNMEASURABLE,
        }
    return out


__all__ = ["UNMEASURABLE", "TAKER", "MAKER", "FRAIS_TAKER_ROUNDTRIP_BPS", "FRAIS_MAKER_ROUNDTRIP_BPS",
           "cout_taker_bps", "position_file_attente", "proba_fill_maker", "net_maker_si_fill_bps",
           "evaluer_execution", "evaluer_matrice", "MATRICE_EXECUTION"]
