"""P1B — VÉRITÉ de latence par exécution causale différée ; le coefficient scalaire n'est qu'un STRESS.

`latency_cost_bps_per_sec × age` ne doit plus être la vérité économique finale. La vérité :

  décision à T → exécution contre le PREMIER carnet causal observé à **T + délai** (délai MESURÉ si on
  l'a, sinon ASSUMED explicitement) ; le coût de latence AUTORITAIRE est le déplacement RÉEL du mid
  entre la décision et ce carnet d'exécution (réutilise `cost_components.latency_bps`).

Deny-by-default : aucun carnet causal à T+délai ⇒ `NO_FILL` ; premier carnet trop tardif (au-delà de la
tolérance) ⇒ `STALE_BOOK` ; un mid manquant ⇒ `UNMEASURABLE`. Le modèle scalaire reste disponible mais
**étiqueté STRESS_ONLY** : il ne peut jamais être promu comme PnL autoritaire. Le MÊME chemin sert en
replay et en forward (sélection déterministe du premier carnet causal). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.simulation.cost_components import latency_bps as _latency_bps

SCHEMA_VERSION = "hypersmart.latency_truth.v1"

MEASURED = "MEASURED"
ASSUMED = "ASSUMED"
NO_FILL = "NO_FILL"
STALE_BOOK = "STALE_BOOK"
UNMEASURABLE = "UNMEASURABLE"
STRESS_ONLY = "STRESS_ONLY"


def _num(x: object) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mid(book: Mapping[str, Any]) -> float | None:
    m = _num(book.get("mid"))
    if m is not None and m > 0:
        return m
    bid, ask = _num(book.get("bid")), _num(book.get("ask"))
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return None


def selectionner_carnet_causal(
    books: Sequence[Mapping[str, Any]], *, decision_ts_ms: float, delay_ms: float, tol_ms: float | None = None
) -> dict[str, Any]:
    """PREMIER carnet observé à ou après `decision_ts_ms + delay_ms`. Déterministe (replay = forward).

    `NO_FILL` si aucun carnet causal ; `STALE_BOOK` si le premier dépasse la tolérance après la cible."""
    d = _num(decision_ts_ms)
    dl = _num(delay_ms)
    if d is None or dl is None:
        return {"statut": UNMEASURABLE, "raison": "decision_ts ou delay manquant"}
    cible = d + dl
    eligibles = sorted(
        (b for b in books if _num(b.get("observed_at_ms")) is not None and _num(b.get("observed_at_ms")) >= cible),
        key=lambda b: _num(b.get("observed_at_ms")),
    )
    if not eligibles:
        return {"statut": NO_FILL, "cible_ms": cible}
    premier = eligibles[0]
    obs = _num(premier.get("observed_at_ms"))
    if tol_ms is not None and (obs - cible) > float(tol_ms):
        return {"statut": STALE_BOOK, "cible_ms": cible, "observed_at_ms": obs, "retard_ms": round(obs - cible, 6)}
    return {"statut": "OK", "carnet": premier, "cible_ms": cible, "observed_at_ms": obs,
            "latency_ms_realise": round(obs - d, 6)}


def latence_scalaire_stress_bps(delay_sec: float, *, coeff_bps_per_sec: float = 0.20, cap_bps: float = 15.0) -> dict[str, Any]:
    """Le modèle scalaire, EXPLICITEMENT `STRESS_ONLY` — jamais un PnL autoritaire."""
    ds = _num(delay_sec)
    if ds is None or ds < 0:
        return {"statut": UNMEASURABLE, "usage": STRESS_ONLY}
    val = min(float(cap_bps), ds * float(coeff_bps_per_sec))
    return {"statut": STRESS_ONLY, "latency_stress_bps": round(val, 6), "usage": STRESS_ONLY,
            "note": "modele de stress, jamais la verite economique finale"}


def verite_latence(
    books: Sequence[Mapping[str, Any]],
    *,
    decision_ts_ms: float,
    mid_decision: float,
    side: object,
    delay_ms: float,
    delay_source: str = ASSUMED,
    tol_ms: float | None = None,
    coeff_stress_bps_per_sec: float = 0.20,
    cap_stress_bps: float = 15.0,
) -> dict[str, Any]:
    """Coût de latence AUTORITAIRE via exécution causale différée + le scalaire en STRESS (jamais promu)."""
    sel = selectionner_carnet_causal(books, decision_ts_ms=decision_ts_ms, delay_ms=delay_ms, tol_ms=tol_ms)
    scalaire = latence_scalaire_stress_bps(
        (_num(delay_ms) or 0.0) / 1000.0, coeff_bps_per_sec=coeff_stress_bps_per_sec, cap_bps=cap_stress_bps)

    base = {"schema_version": SCHEMA_VERSION, "delay_source": (ASSUMED if delay_source != MEASURED else MEASURED),
            "stress_scalaire": scalaire, "real_execution": False}

    if sel["statut"] != "OK":
        base.update({"statut": sel["statut"], "latency_bps_authoritative": None,
                     "execution_mid": None, "latency_ms_realise": sel.get("retard_ms")})
        return base

    carnet = sel["carnet"]
    mid_exec = _mid(carnet)
    lat = _latency_bps(mid_decision, mid_exec, side) if mid_exec is not None else None
    base.update({
        "statut": (MEASURED if lat is not None else UNMEASURABLE),
        "latency_bps_authoritative": lat,          # déplacement RÉEL du mid décision→exécution
        "execution_mid": mid_exec,
        "latency_ms_realise": sel["latency_ms_realise"],
        "execution_observed_at_ms": sel["observed_at_ms"],
    })
    return base


__all__ = [
    "SCHEMA_VERSION", "MEASURED", "ASSUMED", "NO_FILL", "STALE_BOOK", "UNMEASURABLE", "STRESS_ONLY",
    "selectionner_carnet_causal", "latence_scalaire_stress_bps", "verite_latence",
]
