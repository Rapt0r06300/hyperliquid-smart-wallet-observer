"""V13 #159 — Copy-fidelity « réplication d'allocation » + similarity scoring (polybot/polyrec).

Mesure à quel point notre portefeuille PAPER réplique l'ALLOCATION du leader (pas seulement
ses trades). Un faible score = la copie dérive (latence, tailles) → l'edge s'évapore → utile
comme veto/avertissement. Pur / lecture seule ; honnête (état vide) ; 0 ordre.
"""

from __future__ import annotations

from math import sqrt


def allocation_weights(positions: list[dict]) -> dict:
    """{coin: poids} normalisé par |notional| (somme = 1). Vide -> {}."""
    raw: dict[str, float] = {}
    for p in positions or []:
        coin = str(p.get("coin") or p.get("market") or "?").upper()
        side = str(p.get("side") or p.get("direction") or "").upper()
        signed = abs(float(p.get("notional_usdt") or p.get("open_exposure_usdt") or 0.0))
        key = f"{coin}:{'L' if side in {'LONG','BUY'} else 'S' if side in {'SHORT','SELL'} else '?'}"
        raw[key] = raw.get(key, 0.0) + signed
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in raw.items()}


def cosine_similarity(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = sum(float(a.get(k, 0.0)) * float(b.get(k, 0.0)) for k in keys)
    na = sqrt(sum(float(a.get(k, 0.0)) ** 2 for k in keys))
    nb = sqrt(sum(float(b.get(k, 0.0)) ** 2 for k in keys))
    if na <= 0 or nb <= 0:
        return 0.0
    return round(dot / (na * nb), 6)


def allocation_tracking_error(leader: dict, copy: dict) -> float:
    keys = set(leader) | set(copy)
    if not keys:
        return 0.0
    return round(sum(abs(float(leader.get(k, 0.0)) - float(copy.get(k, 0.0))) for k in keys) / len(keys), 6)


def build_replication_score(*, leader_positions: list[dict] | None,
                            copy_positions: list[dict] | None) -> dict:
    la = allocation_weights(leader_positions or [])
    ca = allocation_weights(copy_positions or [])
    if not la and not ca:
        return {"similarity": None, "tracking_error": None, "empty": True,
                "plain_summary": "Pas encore de positions à comparer.", "context_only": True}
    sim = cosine_similarity(la, ca)
    te = allocation_tracking_error(la, ca)
    quality = "fidèle" if sim >= 0.8 else ("moyenne" if sim >= 0.5 else "faible")
    return {
        "similarity": sim, "tracking_error": te,
        "leader_alloc": {k: round(v, 4) for k, v in la.items()},
        "copy_alloc": {k: round(v, 4) for k, v in ca.items()},
        "empty": False, "context_only": True,
        "plain_summary": (f"La copie ressemble à {round(sim*100)}% au portefeuille du leader "
                          f"(fidélité {quality}). Plus c'est haut, mieux on réplique son edge."),
    }


__all__ = ["allocation_weights", "cosine_similarity", "allocation_tracking_error", "build_replication_score"]
