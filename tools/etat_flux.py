"""DATA QUALITY GATE — statuts nommés + taux de qualité (IDEA-3, IDEA-6).

`realtime/feed_quality.FeedQualityGate` calcule déjà l'essentiel (ready/synchronized, score, compteurs).
Ce qui manquait :

  • IDEA-3 : les STATUTS NOMMÉS exigés — FEED_WARMING, FEED_READY, FEED_STALE, FEED_GAP, FEED_RECOVERY,
    FEED_CORRUPTED — avec la règle « rien ne consomme le flux avant FEED_READY », au démarrage ET après
    chaque reconnexion ;
  • IDEA-6 : les TAUX explicites par connexion/flux (stale_rate, gap_rate, duplicate_rate, reconnect_rate,
    out_of_order_rate, snapshot_conflict_rate) en plus des latency/jitter EMA, pour diagnostic, quarantaine
    et reconnexion contrôlée.

Ce module ne duplique pas le gate : il le LIT (dict ou FeedQualitySnapshot) et en dérive un verdict lisible.
0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

#: statuts de flux exigés par IDEA-3 (ordre de gravité croissante après READY).
FEED_WARMING = "FEED_WARMING"
FEED_READY = "FEED_READY"
FEED_STALE = "FEED_STALE"
FEED_GAP = "FEED_GAP"
FEED_RECOVERY = "FEED_RECOVERY"
FEED_CORRUPTED = "FEED_CORRUPTED"
STATUTS = (FEED_WARMING, FEED_READY, FEED_STALE, FEED_GAP, FEED_RECOVERY, FEED_CORRUPTED)

#: raisons qui signent une corruption structurelle (le flux ne peut pas être « juste en retard »).
RAISONS_CORRUPTION = (
    "INVALID_BOOK_LEVEL", "EMPTY_BOOK_SIDE", "CROSSED_OR_LOCKED_BOOK",
    "INCREMENTAL_BEFORE_SNAPSHOT", "INCREMENTAL_UNSUPPORTED_FOR_FULL_SNAPSHOT_FEED",
    "NON_MONOTONIC_EXCHANGE_TIMESTAMP", "NON_MONOTONIC_SEQUENCE", "EXCHANGE_TIMESTAMP_IN_FUTURE",
)


def _d(snap) -> dict:
    """Accepte un FeedQualitySnapshot (dataclass) ou un dict déjà sérialisé."""
    if hasattr(snap, "as_dict"):
        return snap.as_dict()
    return dict(snap or {})


def taux_qualite(snap) -> dict:
    """IDEA-6 — taux par flux, rapportés au nombre total d'événements observés (jamais des compteurs bruts
    présentés comme des taux). `n_total=0` -> taux None (inconnu), jamais 0 flatteur."""
    s = _d(snap)
    n = int(s.get("total_events") or 0)
    def r(cle):
        return (round(float(s.get(cle) or 0) / n, 6) if n > 0 else None)
    return {
        "n_total": n,
        "stale_rate": r("stale_events"),
        "gap_rate": r("gaps"),
        "duplicate_rate": r("duplicates"),
        "reconnect_rate": r("reconnects"),
        "out_of_order_rate": r("non_monotonic"),
        "snapshot_conflict_rate": (
            round(float((s.get("reason_counts") or {}).get("INCREMENTAL_BEFORE_SNAPSHOT", 0)
                        + (s.get("reason_counts") or {}).get("INCREMENTAL_UNSUPPORTED_FOR_FULL_SNAPSHOT_FEED", 0)) / n, 6)
            if n > 0 else None),
        "latency_p50_ms": s.get("latency_p50_ms"), "latency_p95_ms": s.get("latency_p95_ms"),
        "jitter_p95_ms": s.get("jitter_p95_ms"),
        "feed_quality_score": s.get("feed_quality_score"),
    }


def statut_flux(snap, *, min_evenements_coherents: int = 2) -> dict:
    """IDEA-3 — statut nommé du flux + droit de consommer.

    Règles (deny-by-default) :
      FEED_CORRUPTED : une raison de corruption structurelle est présente ;
      FEED_GAP       : trou non résolu (ou gap détecté) — resynchronisation nécessaire ;
      FEED_RECOVERY  : reconnexion en cours de resynchronisation (snapshot pas encore recomposé) ;
      FEED_STALE     : dernier événement/heartbeat trop vieux ;
      FEED_WARMING   : pas encore assez d'événements cohérents (démarrage) ;
      FEED_READY     : synchronisé, frais, sans trou -> SEUL statut consommable."""
    s = _d(snap)
    raisons = list(s.get("reasons") or [])
    compte = dict(s.get("reason_counts") or {})
    corrompu = [r for r in RAISONS_CORRUPTION if r in raisons or compte.get(r)]
    coherents = int(s.get("coherent_events") or 0)
    if corrompu:
        statut, pourquoi = FEED_CORRUPTED, "structure invalide: %s" % ",".join(sorted(corrompu)[:3])
    elif s.get("unresolved_gap") or "TEMPORAL_GAP" in raisons or "SEQUENCE_GAP" in raisons:
        statut, pourquoi = FEED_GAP, "trou non resolu — resynchronisation requise"
    elif "RECONNECT_REQUIRES_RESYNCHRONIZATION" in raisons or (
            int(s.get("reconnects") or 0) > 0 and not s.get("synchronized")):
        statut, pourquoi = FEED_RECOVERY, "reconnexion: snapshot de reprise pas encore recompose"
    elif "LATEST_EVENT_STALE" in raisons or "HEARTBEAT_STALE" in raisons or "STALE_EVENT" in raisons:
        statut, pourquoi = FEED_STALE, "dernier evenement ou heartbeat trop vieux"
    elif not s.get("synchronized") or coherents < int(min_evenements_coherents):
        statut, pourquoi = FEED_WARMING, "pas encore assez d'evenements coherents (%s)" % coherents
    elif s.get("ready"):
        statut, pourquoi = FEED_READY, "synchronise, frais, sans trou"
    else:
        statut, pourquoi = FEED_WARMING, "gate pas encore pret: %s" % ",".join(raisons[:3])
    return {"statut": statut, "pourquoi": pourquoi,
            "peut_consommer": statut == FEED_READY,       # IDEA-3 : rien ne passe avant FEED_READY
            "raisons": raisons[:8], "taux": taux_qualite(s)}


def quarantaine(snap, *, score_min: float = 60.0, stale_rate_max: float = 0.05,
                gap_rate_max: float = 0.02) -> dict:
    """IDEA-6 — décision de quarantaine/reconnexion contrôlée à partir des TAUX (pas d'une impression)."""
    t = taux_qualite(snap)
    motifs = []
    sc = t.get("feed_quality_score")
    if sc is not None and float(sc) < score_min:
        motifs.append("SCORE_TROP_BAS")
    if t.get("stale_rate") is not None and t["stale_rate"] > stale_rate_max:
        motifs.append("TROP_DE_STALE")
    if t.get("gap_rate") is not None and t["gap_rate"] > gap_rate_max:
        motifs.append("TROP_DE_GAPS")
    if t.get("snapshot_conflict_rate"):
        motifs.append("CONFLITS_SNAPSHOT")
    return {"quarantaine": bool(motifs), "motifs": motifs, "taux": t}


__all__ = ["STATUTS", "FEED_WARMING", "FEED_READY", "FEED_STALE", "FEED_GAP", "FEED_RECOVERY",
           "FEED_CORRUPTED", "RAISONS_CORRUPTION", "taux_qualite", "statut_flux", "quarantaine"]
