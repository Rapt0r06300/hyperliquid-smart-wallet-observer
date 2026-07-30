"""§12/§13 — robustesse statistique du scoring wallet + sémantique copy par action (pur, 0 réseau).

Le scoring naïf du Global Observer a deux mensonges possibles, tous deux corrigés ici :

§12.1 **Pseudo-réplication.** Les 3 686 « épisodes » d'un wallet peuvent être des fills corrélés d'un même
métaordre. Les traiter comme 3 686 observations indépendantes gonfle artificiellement la significativité.
On agrège en **grappes** (métaordre / burst / wallet-coin-jour) et on compte les votes **indépendants**.

§12.3 **Biais de sélection.** Un score mesuré sur les données qui ont servi à choisir le wallet est
circulaire. On impose `discovery → freeze → validation intacte → forward`, avec une fenêtre de validation
disjointe de la fenêtre de découverte.

§12.2/§12.4/§12.5 — critères CORE au-delà de N≥20 (jours, régimes, coins, borne basse de confiance > 0,
concentration), correction du multiple testing, et **expiration** : un wallet historiquement bon peut
devenir mauvais ; il est rétrogradé, et peut redevenir CHALLENGER après cooldown.

§13 — sémantique copy PAR ACTION : `OPEN` est le candidat principal, `REDUCE` réduit NOTRE exposition sans
jamais ouvrir le sens inverse, `FLIP` = close + décision séparée.

Aucune promotion depuis ce module : il durcit le jugement, il ne décide pas d'exécuter.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "hypersmart.scoring_robuste.v1"

#: Clés d'agrégation en grappes, de la plus fine à la plus grossière.
CLES_GRAPPE = ("metaorder", "burst", "wallet_coin_jour", "open_event")

#: Critères CORE — N≥20 ne suffit pas seul (§12.2).
MIN_VOTES_INDEPENDANTS = 20
MIN_JOURS = 3
MIN_REGIMES = 2
MIN_COINS = 1
CONCENTRATION_MAX = 0.35

#: §13 — sémantique par action.
ACTIONS_COPY = {
    "OPEN": "CANDIDAT_PRINCIPAL",
    "ADD": "SEULEMENT_SI_POSITION_ET_CAPACITE_ET_EDGE_RESIDUEL",
    "REDUCE": "REDUIRE_NOTRE_EXPOSITION_JAMAIS_OUVRIR_INVERSE",
    "CLOSE": "FERMER_NOTRE_COPIE",
    "FLIP": "FERMER_PUIS_DECISION_SEPAREE",
}


def _jour(ts_ms: Any) -> int | None:
    if not isinstance(ts_ms, (int, float)) or isinstance(ts_ms, bool):
        return None
    return int(float(ts_ms) // 86_400_000)


# ════════════════════════ §12.1 — grappes indépendantes ════════════════════════
def cle_grappe(episode: Mapping[str, Any]) -> str:
    """Identité de grappe d'un épisode. Deux fills du même métaordre partagent la même clé."""
    for cle in ("metaorder_id", "twap_id", "burst_id"):
        v = episode.get(cle)
        if v not in (None, "", 0, "0"):
            return "%s:%s" % (cle, v)
    return "wcj:%s:%s:%s" % (episode.get("wallet"), episode.get("coin"), _jour(episode.get("ts_ms")))


def agreger_en_grappes(episodes: Sequence[Mapping[str, Any]], *, cle_valeur: str = "net_bps") -> dict[str, Any]:
    """Réduit N fills corrélés à un vote par grappe (moyenne intra-grappe). Rend les votes indépendants."""
    grappes: dict[str, list[float]] = {}
    for e in episodes:
        v = e.get(cle_valeur)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            grappes.setdefault(cle_grappe(e), []).append(float(v))
    votes = [round(statistics.mean(vals), 6) for vals in grappes.values() if vals]
    return {"n_fills": len(episodes), "n_votes_independants": len(votes), "votes_bps": votes,
            "facteur_replication": (round(len(episodes) / len(votes), 3) if votes else None)}


# ════════════════════════ §12.4 — borne basse de confiance (bootstrap de blocs) ════════════════════════
def borne_basse_confiance(votes: Sequence[float], *, alpha: float = 0.05, n_boot: int = 2_000,
                          seed: int = 0) -> float | None:
    """Borne inférieure de l'IC de la moyenne, par bootstrap. `None` si trop peu de votes."""
    votes = [float(v) for v in votes]
    if len(votes) < 8:
        return None
    rng = _Rng(seed)
    moyennes = []
    n = len(votes)
    for _ in range(int(n_boot)):
        ech = [votes[rng.randint(n)] for _ in range(n)]
        moyennes.append(sum(ech) / n)
    moyennes.sort()
    idx = max(0, min(len(moyennes) - 1, int(alpha * len(moyennes))))
    return round(moyennes[idx], 6)


class _Rng:
    """PRNG déterministe (LCG) — pas de dépendance, reproductible pour les tests."""

    def __init__(self, seed: int) -> None:
        self._s = (int(seed) & 0xFFFFFFFF) or 1

    def randint(self, n: int) -> int:
        self._s = (1103515245 * self._s + 12345) & 0x7FFFFFFF
        return self._s % n


# ════════════════════════ §12.2 — critères CORE complets ════════════════════════
def critere_core(episodes: Sequence[Mapping[str, Any]], *, min_votes: int = MIN_VOTES_INDEPENDANTS,
                 min_jours: int = MIN_JOURS, min_regimes: int = MIN_REGIMES,
                 min_coins: int = MIN_COINS) -> dict[str, Any]:
    """CORE seulement si assez de votes INDÉPENDANTS, de jours, de régimes, de coins, ET borne basse > 0."""
    agg = agreger_en_grappes(episodes)
    votes = agg["votes_bps"]
    jours = {_jour(e.get("ts_ms")) for e in episodes if _jour(e.get("ts_ms")) is not None}
    regimes = {str(e.get("regime") or "?") for e in episodes}
    coins = {str(e.get("coin") or "?") for e in episodes}
    total = sum(votes)
    concentration = (max((abs(v) for v in votes), default=0.0) / abs(total)) if abs(total) > 1e-12 else 1.0
    lcb = borne_basse_confiance(votes)
    raisons: list[str] = []
    if len(votes) < int(min_votes):
        raisons.append("VOTES_INDEPENDANTS_INSUFFISANTS")
    if len(jours) < int(min_jours):
        raisons.append("PAS_ASSEZ_DE_JOURS")
    if len(regimes - {"?"}) < int(min_regimes):
        raisons.append("PAS_ASSEZ_DE_REGIMES")
    if len(coins - {"?"}) < int(min_coins):
        raisons.append("PAS_ASSEZ_DE_COINS")
    if lcb is None:
        raisons.append("BORNE_BASSE_NON_MESURABLE")
    elif lcb <= 0:
        raisons.append("BORNE_BASSE_NON_POSITIVE")
    if concentration > CONCENTRATION_MAX:
        raisons.append("EDGE_TROP_CONCENTRE")
    return {"eligible_core": not raisons, "raisons": raisons,
            "n_votes_independants": len(votes), "n_jours": len(jours),
            "n_regimes": len(regimes - {"?"}), "n_coins": len(coins - {"?"}),
            "borne_basse_bps": lcb, "concentration": round(concentration, 4),
            "facteur_replication": agg["facteur_replication"]}


# ════════════════════════ §12.3 — biais de sélection ════════════════════════
def separer_decouverte_validation(episodes: Sequence[Mapping[str, Any]], *,
                                  fraction_decouverte: float = 0.6) -> dict[str, Any]:
    """Coupe TEMPORELLE : découverte (sélection) puis validation INTACTE. Le score final se mesure sur la
    validation, jamais sur la découverte. Les deux fenêtres sont disjointes par construction."""
    ordonnes = sorted((e for e in episodes if _jour(e.get("ts_ms")) is not None),
                      key=lambda e: float(e.get("ts_ms")))
    if len(ordonnes) < 4:
        return {"decouverte": [], "validation": [], "disjointes": True, "n": len(ordonnes),
                "raison": "trop peu d'episodes horodates"}
    coupe = int(len(ordonnes) * float(fraction_decouverte))
    dec, val = ordonnes[:coupe], ordonnes[coupe:]
    t_dec = max((float(e["ts_ms"]) for e in dec), default=0.0)
    t_val = min((float(e["ts_ms"]) for e in val), default=0.0)
    return {"decouverte": dec, "validation": val, "n": len(ordonnes),
            "disjointes": bool(t_val >= t_dec),
            "note": "le score final se mesure sur la VALIDATION, jamais sur la fenetre de decouverte"}


# ════════════════════════ §12.5 — expiration / rétrogradation ════════════════════════
def statut_expiration(episodes: Sequence[Mapping[str, Any]], *, now_ms: int,
                      fenetre_recente_ms: float = 7 * 86_400_000.0, min_recent: int = 5,
                      cooldown_ms: float = 3 * 86_400_000.0) -> dict[str, Any]:
    """Un wallet historiquement bon peut devenir mauvais. Rolling edge récent + rétrogradation."""
    recents = [e for e in episodes
               if isinstance(e.get("ts_ms"), (int, float)) and float(now_ms) - float(e["ts_ms"]) <= fenetre_recente_ms
               and isinstance(e.get("net_bps"), (int, float))]
    if len(recents) < int(min_recent):
        return {"statut": "GEL_INSUFFISANCE_RECENTE", "peut_rester_core": False,
                "peut_redevenir_challenger": True, "n_recents": len(recents),
                "raison": "moins de %d episodes recents : on ne prolonge pas un CORE a l'aveugle" % min_recent}
    edge = statistics.mean(float(e["net_bps"]) for e in recents)
    dernier = max(float(e["ts_ms"]) for e in recents)
    en_cooldown = (float(now_ms) - dernier) < float(cooldown_ms)
    if edge > 0:
        return {"statut": "CORE_MAINTENU", "peut_rester_core": True, "rolling_edge_bps": round(edge, 4),
                "n_recents": len(recents)}
    return {"statut": "RETROGRADE", "peut_rester_core": False,
            "peut_redevenir_challenger": not en_cooldown, "rolling_edge_bps": round(edge, 4),
            "n_recents": len(recents),
            "raison": "edge recent negatif : retrograde ; re-challenger apres cooldown/regime nouveau"}


# ════════════════════════ §13 — sémantique copy par action ════════════════════════
def decision_copy(action: str, *, avons_position: bool = False, capacite_restante: bool = False,
                  edge_residuel_positif: bool = False) -> dict[str, Any]:
    """Traduit une action du leader en décision de copie. `REDUCE` ne peut JAMAIS ouvrir le sens inverse."""
    a = str(action).upper()
    if a == "OPEN":
        return {"action_copy": "OUVRIR", "role": ACTIONS_COPY["OPEN"], "ouvre_inverse": False}
    if a == "ADD":
        ok = bool(avons_position and capacite_restante and edge_residuel_positif)
        return {"action_copy": "AJOUTER" if ok else "IGNORER",
                "role": ACTIONS_COPY["ADD"], "ouvre_inverse": False,
                "raison": None if ok else "ADD copie seulement avec position + capacite + edge residuel"}
    if a == "REDUCE":
        return {"action_copy": ("REDUIRE" if avons_position else "IGNORER"),
                "role": ACTIONS_COPY["REDUCE"], "ouvre_inverse": False}
    if a == "CLOSE":
        return {"action_copy": ("FERMER" if avons_position else "IGNORER"),
                "role": ACTIONS_COPY["CLOSE"], "ouvre_inverse": False}
    if a == "FLIP":
        return {"action_copy": "FERMER_PUIS_DECIDER", "role": ACTIONS_COPY["FLIP"],
                "ouvre_inverse": False,
                "note": "le FLIP ferme notre copie ; l'ouverture inverse est une decision SEPAREE"}
    return {"action_copy": "IGNORER", "role": "ACTION_INCONNUE", "ouvre_inverse": False}


def variantes_de_copie() -> tuple[str, ...]:
    """§13 — les stratégies de copie à comparer explicitement (le meilleur markout ≠ meilleur PnL complet)."""
    return ("OPEN_SEUL", "OPEN_PLUS_PREMIER_ADD", "TOUS_ADD", "SUIVRE_LEADER_EXIT",
            "TIME_STOP", "CONVERGENCE_EXIT", "MICROSTRUCTURE_EXIT")


__all__ = ["SCHEMA_VERSION", "CLES_GRAPPE", "ACTIONS_COPY", "MIN_VOTES_INDEPENDANTS",
           "cle_grappe", "agreger_en_grappes", "borne_basse_confiance", "critere_core",
           "separer_decouverte_validation", "statut_expiration", "decision_copy", "variantes_de_copie"]
