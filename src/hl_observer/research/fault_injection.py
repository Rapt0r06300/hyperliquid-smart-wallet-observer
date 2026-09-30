"""FIX-56 — INJECTION DE FAUTES : prouver que le système DÉGRADE honnêtement sous chaque panne, sans jamais
fabriquer de gain ni exploiter une donnée corrompue.

Taxonomie complète : WS_DISCONNECT, GAP (trou source), DUPLICATE, OUT_OF_ORDER, STALE (carnet périmé),
PROVIDER_OUTAGE (silence total), CORRUPT_LEDGER (ledger illisible/invariant cassé), DISK_ERROR (I/O).

Invariant de robustesse (flux) : une faute peut au pire FAIRE PERDRE une opportunité (donnée écartée), JAMAIS
créer un fill fantôme ni planter. On le vérifie en rejouant le flux fauté dans le MÊME pipeline canonique
(FIX-44) et en exigeant : fills_injectés ⊆ fills_propres (0 fantôme) et 0 crash.
Invariant ledger/disk : lecture fail-closed — un ledger corrompu ou un I/O échoué rend un statut d'erreur,
JAMAIS un PnL inventé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.ops.paper_pipeline_e2e import executer_forward

FAUTES = ("WS_DISCONNECT", "GAP", "DUPLICATE", "OUT_OF_ORDER", "STALE", "PROVIDER_OUTAGE",
          "CORRUPT_LEDGER", "DISK_ERROR")
FAUTES_FLUX = ("WS_DISCONNECT", "GAP", "DUPLICATE", "OUT_OF_ORDER", "STALE", "PROVIDER_OUTAGE")


def injecter(events: Sequence[Mapping[str, Any]], faute: str) -> list[dict[str, Any]]:
    """Injecte `faute` dans un flux d'événements propres et rend le flux fauté (les événements sont copiés)."""
    evs = [dict(e) for e in events]
    idx_signal = next((i for i, e in enumerate(evs) if e.get("strategy")), None)
    if faute == "DUPLICATE":
        out: list[dict[str, Any]] = []
        for e in evs:
            out.append(e)
            if e.get("strategy"):
                out.append(dict(e))                      # doublon exact (même seq) -> doit être dédupliqué
        return out
    if faute == "OUT_OF_ORDER" and idx_signal is not None and idx_signal + 2 < len(evs):
        e = evs.pop(idx_signal)
        evs.insert(idx_signal + 2, e)                    # arrive après des seq plus grandes -> hors-ordre
        return evs
    if faute == "GAP" and idx_signal is not None:
        evs.pop(idx_signal)                              # trou à la source : un événement manque
        return evs
    if faute == "STALE":
        for e in evs:
            if e.get("strategy"):
                e["book_ts_ms"] = -10_000_000            # carnet très vieux -> STALE -> jamais exploité
        return evs
    if faute == "WS_DISCONNECT":
        n = len(evs)
        return evs[: n // 3] + evs[2 * n // 3:]          # coupure : bloc central perdu (reconnexion plus loin)
    if faute == "PROVIDER_OUTAGE":
        return []                                        # silence total du provider
    return evs


def resilience_stream(events_propres: Sequence[Mapping[str, Any]], faute: str, **kw: Any) -> dict[str, Any]:
    """Rejoue le flux propre puis le flux fauté dans le MÊME pipeline canonique. Robuste ssi aucun fill fantôme
    (fills_injectés ⊆ fills_propres) et aucun crash."""
    propre = executer_forward(events_propres, **kw)
    seqs_propres = {d["seq"] for d in propre.decisions if d["decision"] == "FILL"}
    crash = False
    seqs_inj: set[Any] = set()
    try:
        injecte = executer_forward(injecter(events_propres, faute), **kw)
        seqs_inj = {d["seq"] for d in injecte.decisions if d["decision"] == "FILL"}
    except Exception:                                    # un flux fauté ne DOIT jamais faire planter le moteur
        crash = True
    phantom = sorted(seqs_inj - seqs_propres)
    return {"faute": faute, "crash": crash, "phantom": phantom,
            "fills_propres": len(seqs_propres), "fills_injectes": len(seqs_inj),
            "robuste": (not crash and not phantom)}


def verifier_ledger(lignes: Sequence[Any]) -> dict[str, Any]:
    """Ledger fail-closed : une ligne JSON invalide ou l'invariant equity=cash+positions cassé => CORROMPU
    (jamais un PnL servi en douce)."""
    for i, ln in enumerate(lignes):
        try:
            r = json.loads(ln) if isinstance(ln, (str, bytes)) else dict(ln)
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"statut": "CORROMPU", "ligne": i, "raison": "JSON invalide"}
        if all(k in r for k in ("equity", "cash", "positions_val")):
            try:
                casse = abs(float(r["equity"]) - (float(r["cash"]) + float(r["positions_val"]))) > 1e-6
            except (TypeError, ValueError):
                return {"statut": "CORROMPU", "ligne": i, "raison": "champs non numériques"}
            if casse:
                return {"statut": "CORROMPU", "ligne": i, "raison": "invariant equity=cash+positions cassé"}
    return {"statut": "OK", "n": len(lignes)}


def lire_ledger(path: str) -> dict[str, Any]:
    """Lecture robuste d'un ledger sur disque : toute erreur I/O => DISK_ERROR (fail-closed, jamais de PnL inventé)."""
    try:
        with open(path, encoding="utf-8") as f:
            lignes = [ln for ln in f if ln.strip()]
    except OSError as exc:
        return {"statut": "DISK_ERROR", "raison": type(exc).__name__}
    return verifier_ledger(lignes)


__all__ = ["FAUTES", "FAUTES_FLUX", "injecter", "resilience_stream", "verifier_ledger", "lire_ledger"]
