"""ALPHA P9 — REPLAY = FORWARD : le même pipeline métier doit donner le MÊME résultat en replay et en forward.

Invariants testables : déterminisme (même intent+snapshot+config → même fill/PnL), stabilité de préfixe
(tronquer le futur ne change pas les décisions passées), robustesse aux doublons / out-of-order / carnet
périmé (ils sont filtrés, pas exploités). Ici les VÉRIFICATEURS ; le moteur reste `paper_engine` (causal).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def deterministe(resultats_run1: Sequence[Any], resultats_run2: Sequence[Any]) -> bool:
    """Même entrées → mêmes sorties (fills/PnL identiques)."""
    return list(resultats_run1) == list(resultats_run2)


def prefix_stable(decisions_complet: Sequence[Any], decisions_prefixe: Sequence[Any]) -> bool:
    """Tronquer le futur ne doit pas altérer les décisions passées."""
    k = len(decisions_prefixe)
    return list(decisions_complet[:k]) == list(decisions_prefixe)


def filtre_evenements(events: Sequence[dict], *, dernier_seq: int = -1, book_max_age_ms: float = 5000.0,
                      now_ms: float | None = None) -> dict[str, Any]:
    """Filtre doublons (seq déjà vue), out-of-order (seq < dernier), carnet périmé (âge > max). Rien d'exploité en douce."""
    gardes, rejets = [], {"doublon": 0, "out_of_order": 0, "stale": 0}
    vus: set[int] = set()
    d = dernier_seq
    for e in events:
        s = e.get("seq")
        if isinstance(s, (int, float)):
            if s in vus:
                rejets["doublon"] += 1
                continue
            if s < d:
                rejets["out_of_order"] += 1
                continue
            vus.add(s); d = max(d, s)
        if now_ms is not None and isinstance(e.get("book_ts_ms"), (int, float)):
            if now_ms - e["book_ts_ms"] > book_max_age_ms:
                rejets["stale"] += 1
                continue
        gardes.append(e)
    return {"gardes": gardes, "n_gardes": len(gardes), "rejets": rejets}


#: FIX-14 — taxonomie des désynchronisations de données (un événement corrompu n'est JAMAIS exploité en douce).
DESYNC_TYPES = ("OK", "SCHEMA", "DUPLICATE", "ORDERING", "SOURCE_GAP", "STALE", "BOOTSTRAP")


def classer_desync(events: Sequence[dict], *, champs_requis: Sequence[str] = ("seq",),
                   book_max_age_ms: float = 5000.0, now_ms: float | None = None,
                   seq_gap_max: int = 1) -> dict[str, Any]:
    """FIX-14 — classe CHAQUE événement du flux selon son type de désync, pour ne jamais confondre une donnée
    saine avec une donnée rejouée / hors-ordre / issue d'un backfill / trouée.

    Types (priorité décroissante) : SCHEMA (champ requis manquant ou seq invalide) ; DUPLICATE (seq déjà vue) ;
    ORDERING (seq < dernière) ; BOOTSTRAP (snapshot/backfill, pas du live frais) ; STALE (carnet trop vieux) ;
    SOURCE_GAP (saut de seq > `seq_gap_max` = événements/fills manquants à la source) ; OK (propre). Seuls les
    OK sont « propres » ; SOURCE_GAP est accepté mais signalé (des événements manquent AUTOUR, pas celui-ci)."""
    labels: list[str] = []
    compteur = {t: 0 for t in DESYNC_TYPES}
    propres: list[dict] = []
    vus: set[float] = set()
    dernier: float | None = None
    for e in events:
        seq = e.get("seq")
        seq_ok = isinstance(seq, (int, float)) and not isinstance(seq, bool)
        manque = [c for c in champs_requis if e.get(c) is None]
        if manque or not seq_ok:
            lab = "SCHEMA"
        elif seq in vus:
            lab = "DUPLICATE"
        elif dernier is not None and seq < dernier:
            lab = "ORDERING"
        elif e.get("bootstrap") or e.get("is_snapshot"):
            lab = "BOOTSTRAP"
        elif (now_ms is not None and isinstance(e.get("book_ts_ms"), (int, float))
              and now_ms - e["book_ts_ms"] > book_max_age_ms):
            lab = "STALE"
        elif dernier is not None and (seq - dernier) > seq_gap_max:
            lab = "SOURCE_GAP"
        else:
            lab = "OK"
        if seq_ok and lab not in ("SCHEMA", "DUPLICATE", "ORDERING"):
            vus.add(seq)
            dernier = seq if dernier is None else max(dernier, seq)
        labels.append(lab)
        compteur[lab] += 1
        if lab == "OK":
            propres.append(e)
    return {"labels": labels, "compteur": compteur, "propres": propres,
            "n_propres": len(propres), "n_total": len(events)}


__all__ = ["deterministe", "prefix_stable", "filtre_evenements", "classer_desync", "DESYNC_TYPES"]
