"""FORWARD PAPER CAUSAL — SIGNAL_READY / EPISODE_MATURED, file globale, capital partagé (IDEA-27 → 32).

`forward_portefeuille` sait déjà rejouer un forward à capital partagé et persister les sorties. Ce module
ajoute la MACHINE D'ÉTAT causale qui manquait, celle qui rend le PnL défendable :

  • IDEA-27 : SIGNAL_READY (T0 : signal + entrée exécutable + OPEN) est STRICTEMENT séparé de
    EPISODE_MATURED (T1 : la sortie est observée). Le futur ne conditionne jamais rétroactivement l'OPEN ;
  • IDEA-28 : l'OPEN est écrit AVANT de connaître la sortie, la position est persistée avec son horizon et
    son exit_due_ts, et fermée quand le futur arrive vraiment (STATEFUL_FORWARD_PAPER, à ne pas confondre
    avec un PROSPECTIVE_MATURED_REPLAY où l'on connaît déjà l'issue) ;
  • IDEA-29 : une file CHRONOLOGIQUE globale multi-candidats (clé = timestamp marché, puis candidate_id) —
    jamais l'ordre de la boucle Python ;
  • IDEA-30 : concurrence RÉELLE du capital — le premier signal chronologique sert, les autres sont refusés
    faute de capital, quel que soit l'ordre du registre ;
  • IDEA-31 : chaque position porte horizon_ms, exit_due_ts, candidate_id, exit_rule et reste
    RECONSTRUCTIBLE même si le fichier des sorties en attente est corrompu ;
  • IDEA-32 : sortie non mesurable = EXIT_UNMEASURABLE/DATA_GAP + politique conservatrice pré-enregistrée —
    la position n'est JAMAIS supprimée en silence.

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import json
from pathlib import Path

SIGNAL_READY = "SIGNAL_READY"
EPISODE_MATURED = "EPISODE_MATURED"
EXIT_UNMEASURABLE = "EXIT_UNMEASURABLE"
DATA_GAP = "DATA_GAP"
ETATS = (SIGNAL_READY, EPISODE_MATURED, EXIT_UNMEASURABLE, DATA_GAP)

#: modes de rejeu — à ne jamais confondre dans un rapport (IDEA-28).
STATEFUL_FORWARD_PAPER = "STATEFUL_FORWARD_PAPER"           # OPEN écrit avant de connaître l'issue
PROSPECTIVE_MATURED_REPLAY = "PROSPECTIVE_MATURED_REPLAY"   # issue déjà connue au moment du rejeu

#: politiques pré-enregistrées pour une sortie non mesurable (IDEA-32). Choisies AVANT de voir les résultats.
POLITIQUES_SORTIE_MANQUANTE = ("CONSERVATEUR_PERTE_MAX", "GARDER_OUVERT", "EXCLURE_DU_PNL")
POLITIQUE_DEFAUT = "CONSERVATEUR_PERTE_MAX"


def ouvrir_signal(*, candidate_id: str, coin: str, sens: int, ts_signal_ms: float, horizon_ms: float,
                  entry_px: float, notional: float, exit_rule: str = "HORIZON") -> dict:
    """IDEA-27/28/31 — crée un OPEN à T0. Aucune information de sortie n'est acceptée ici : la signature
    ne la prend même pas. La position porte tout ce qu'il faut pour être reconstruite (IDEA-31)."""
    if entry_px is None or float(entry_px) <= 0:
        raise ValueError("entry_px invalide: un OPEN exige un prix executable")
    if float(notional) <= 0:
        raise ValueError("notional invalide")
    ts = float(ts_signal_ms)
    h = float(horizon_ms)
    return {"etat": SIGNAL_READY, "candidate_id": str(candidate_id), "coin": coin,
            "sens": (1 if int(sens) >= 0 else -1), "ts_signal_ms": ts, "horizon_ms": h,
            "exit_due_ts": ts + h,                            # échéance connue, RÉSULTAT inconnu
            "entry_px": float(entry_px), "notional": float(notional), "exit_rule": str(exit_rule),
            "position_id": "%s:%d" % (candidate_id, int(ts)),
            "exit_px": None, "net_bps": None, "mode": STATEFUL_FORWARD_PAPER}


def maturer(position: dict, *, maintenant_ms: float, prix_sortie=None,
            politique: str = POLITIQUE_DEFAUT, perte_max_bps: float = 50.0) -> dict:
    """IDEA-27/32 — tente de fermer une position À SON ÉCHÉANCE seulement.

    • échéance non atteinte  -> reste SIGNAL_READY (on ne ferme pas par anticipation) ;
    • prix de sortie présent -> EPISODE_MATURED avec net_bps mesuré ;
    • prix absent            -> EXIT_UNMEASURABLE (+ DATA_GAP) et application de la politique
      PRÉ-ENREGISTRÉE : la position n'est jamais supprimée."""
    p = dict(position)
    if float(maintenant_ms) < float(p["exit_due_ts"]):
        return {**p, "etat": SIGNAL_READY, "motif": "ECHEANCE_NON_ATTEINTE"}
    if politique not in POLITIQUES_SORTIE_MANQUANTE:
        raise ValueError("politique de sortie inconnue: %s" % politique)
    try:
        px = float(prix_sortie)
    except (TypeError, ValueError):
        px = None
    if px is None or px <= 0:
        net = None
        if politique == "CONSERVATEUR_PERTE_MAX":
            net = -abs(float(perte_max_bps))                  # hypothèse défavorable, jamais un 0 flatteur
        return {**p, "etat": EXIT_UNMEASURABLE, "sous_etat": DATA_GAP, "politique": politique,
                "net_bps": net, "exit_px": None, "promotable": False,
                "motif": "carnet futur absent a l'echeance — position CONSERVEE"}
    net = p["sens"] * (px - p["entry_px"]) / p["entry_px"] * 1e4
    return {**p, "etat": EPISODE_MATURED, "exit_px": px, "net_bps": round(net, 4),
            "ts_sortie_ms": float(maintenant_ms), "promotable": True}


def file_chronologique(signaux) -> list:
    """IDEA-29 — ordre GLOBAL déterministe : (ts marché, candidate_id). L'ordre d'itération Python, l'ordre
    du registre ou l'ordre d'insertion n'influencent JAMAIS le résultat."""
    return sorted(list(signaux or []),
                  key=lambda s: (float(s.get("ts_signal_ms", s.get("entry_ts", 0)) or 0),
                                 str(s.get("candidate_id", s.get("trial_id", "")))))


def allouer_capital(signaux, *, capital: float, marge_par_trade: float) -> dict:
    """IDEA-30 — concurrence RÉELLE : on sert dans l'ordre CHRONOLOGIQUE jusqu'à épuisement du capital.
    Le même jeu de signaux donne le même résultat quel que soit l'ordre d'entrée (test de permutation)."""
    ordre = file_chronologique(signaux)
    reste = float(capital)
    m = float(marge_par_trade)
    acceptes, refuses = [], []
    for s in ordre:
        if m <= reste + 1e-12:
            reste -= m
            acceptes.append({**s, "alloue": True})
        else:
            refuses.append({**s, "alloue": False, "motif": "CAPITAL_INSUFFISANT"})
    return {"acceptes": acceptes, "refuses": refuses, "capital_restant": round(reste, 6),
            "n_acceptes": len(acceptes), "n_refuses": len(refuses)}


class SortiesReconstructibles:
    """IDEA-31 — sorties en attente persistées ET reconstructibles. Si le fichier est corrompu, on ne perd
    aucune sortie : on la reconstruit depuis les positions ouvertes (chacune porte son exit_due_ts)."""

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)

    def ecrire(self, positions) -> int:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        lignes = [{"position_id": p["position_id"], "candidate_id": p["candidate_id"],
                   "exit_due_ts": p["exit_due_ts"], "horizon_ms": p["horizon_ms"],
                   "exit_rule": p.get("exit_rule", "HORIZON")} for p in positions]
        self.chemin.write_text(json.dumps(lignes, ensure_ascii=False), encoding="utf-8")
        return len(lignes)

    def lire(self) -> list:
        try:
            data = json.loads(self.chemin.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def reconstruire(self, positions_ouvertes) -> dict:
        """Si le fichier est illisible/incomplet, on RECONSTRUIT depuis les positions (aucune sortie perdue)."""
        sur_disque = {x.get("position_id") for x in self.lire()}
        manquantes = [p for p in (positions_ouvertes or []) if p.get("position_id") not in sur_disque]
        if manquantes:
            self.ecrire(list(positions_ouvertes))
        return {"n_sur_disque": len(sur_disque), "n_reconstruites": len(manquantes),
                "corrige": bool(manquantes)}


__all__ = ["SIGNAL_READY", "EPISODE_MATURED", "EXIT_UNMEASURABLE", "DATA_GAP", "ETATS",
           "STATEFUL_FORWARD_PAPER", "PROSPECTIVE_MATURED_REPLAY", "POLITIQUES_SORTIE_MANQUANTE",
           "POLITIQUE_DEFAUT", "ouvrir_signal", "maturer", "file_chronologique", "allouer_capital",
           "SortiesReconstructibles"]
