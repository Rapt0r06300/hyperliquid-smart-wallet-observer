"""P1B — contrat UNIQUE coûts/latence : un coût compté UNE fois, chaque latence étiquetée honnêtement.

Deux règles de la roadmap, réunies car indissociables :

§3.3 — **une seule convention de coûts, aucun double comptage.** Le prix de fill = vrai prix du carnet
observé à l'instant simulé d'exécution ; spread & slippage **émergent** de ce prix (donc `included_in_price`)
et ne doivent PAS être re-déduits ; les frais sont un coût **explicite** (déduit une fois) ; la latence est
le déplacement entre snapshot de décision et snapshot d'exécution — si le fill est déjà exécuté contre le
carnet causal futur, la latence est DANS le prix ; y ajouter en plus une taxe scalaire = double comptage.

§3.4 — **séparer les concepts de latence.** Ne plus appeler « latence réelle » un coefficient statique.
Chaque segment est publié séparément et étiqueté : `MEASURED` (calculé de deux horodatages réels
cohérents), `ASSUMED` (délai supposé/config, ex. exécution externe), `UNMEASURABLE` (un horodatage
manque — jamais 0, jamais MEASURED). Aucune promotion ne peut s'appuyer sur de l'ASSUMED déguisé en
MEASURED. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hl_observer.simulation.cost_components import latency_bps as _latency_bps

SCHEMA_VERSION = "hypersmart.cost_latency_contract.v1"

MEASURED = "MEASURED"
ASSUMED = "ASSUMED"
UNMEASURABLE = "UNMEASURABLE"

#: Segments décision→exécution, chacun = (horodatage_début, horodatage_fin). Ordre causal.
_SEGMENTS = (
    ("exchange_to_receive_ms", "exchange_ts_ms", "receive_ts_ms"),
    ("receive_to_normalize_ms", "receive_ts_ms", "normalize_ts_ms"),
    ("normalize_to_signal_ms", "normalize_ts_ms", "signal_ts_ms"),
    ("signal_to_gate_ms", "signal_ts_ms", "gate_ts_ms"),
    ("gate_to_paper_submit_ms", "gate_ts_ms", "paper_submit_ts_ms"),
    ("decision_to_fill_ms", "decision_ts_ms", "fill_ts_ms"),
)


def _num(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _segment(debut: object, fin: object) -> dict[str, Any]:
    d, f = _num(debut), _num(fin)
    if d is None or f is None:
        return {"value_ms": None, "statut": UNMEASURABLE}
    delta = f - d
    if delta < 0:
        # Horodatages incohérents : on ne fabrique pas une latence négative « mesurée ».
        return {"value_ms": None, "statut": UNMEASURABLE, "note": "HORODATAGE_INCOHERENT"}
    return {"value_ms": round(delta, 6), "statut": MEASURED}


def taxonomie_latence(
    timestamps: Mapping[str, Any],
    *,
    assumed_external_execution_ms: float | None = None,
    signal_age_ms: float | None = None,
    mid_decision: float | None = None,
    mid_fill: float | None = None,
    side: object = None,
) -> dict[str, Any]:
    """Publie chaque segment de latence séparément avec son étiquette MEASURED/ASSUMED/UNMEASURABLE.

    `timestamps` : mapping des horodatages disponibles (exchange_ts_ms, receive_ts_ms, …, fill_ts_ms).
    Aucun horodatage manquant n'est remplacé par `now` : absence ⇒ segment UNMEASURABLE.
    """
    ts = timestamps or {}
    out: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    for nom, debut, fin in _SEGMENTS:
        out[nom] = _segment(ts.get(debut), ts.get(fin))

    # signal_age_ms : mesuré si fourni (observed − leader event) ; sinon dérivable des ts si présents.
    if signal_age_ms is not None and _num(signal_age_ms) is not None:
        out["signal_age_ms"] = {"value_ms": round(float(signal_age_ms), 6), "statut": MEASURED}
    else:
        out["signal_age_ms"] = _segment(ts.get("leader_event_ts_ms"), ts.get("observed_ts_ms"))

    # assumed_external_execution_ms : c'est une HYPOTHÈSE, jamais MEASURED.
    aee = _num(assumed_external_execution_ms)
    out["assumed_external_execution_ms"] = (
        {"value_ms": round(aee, 6), "statut": ASSUMED} if aee is not None
        else {"value_ms": None, "statut": UNMEASURABLE}
    )

    # latency_markout_bps : dérive ADVERSE du mid décision→exécution (réutilise cost_components).
    lm = _latency_bps(mid_decision, mid_fill, side) if (mid_decision is not None and mid_fill is not None) else None
    out["latency_markout_bps"] = (
        {"value_bps": lm, "statut": MEASURED} if lm is not None
        else {"value_bps": None, "statut": UNMEASURABLE}
    )

    out["unmeasurable"] = tuple(k for k, v in out.items()
                                if isinstance(v, dict) and v.get("statut") == UNMEASURABLE)
    out["real_execution"] = False
    return out


@dataclass(frozen=True, slots=True)
class ComposanteCout:
    name: str
    bps: float
    included_in_price: bool     # True = déjà dans le prix de fill (spread/slippage/latence causale)


@dataclass(frozen=True, slots=True)
class VerificationCouts:
    net_bps: float | None
    double_comptes: tuple[str, ...]
    verdict: str                # OK | DOUBLE_COMPTE | UNMEASURABLE
    deductions_explicites: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "net_bps": self.net_bps,
            "double_comptes": list(self.double_comptes), "verdict": self.verdict,
            "deductions_explicites": list(self.deductions_explicites), "real_execution": False,
        }


def verifier_convention_couts(gross_edge_bps: float | None, composantes: Sequence[ComposanteCout]) -> VerificationCouts:
    """Vérifie qu'AUCUN coût n'est compté deux fois et calcule le net selon la convention unique.

    - un coût `included_in_price=True` est DÉJÀ dans le prix (donc dans le gross) : il n'est pas re-déduit ;
    - un coût `included_in_price=False` est déduit **une** fois ;
    - un même `name` présent des DEUX façons (une fois dans le prix, une fois explicite) = DOUBLE_COMPTE.
    `net_bps` = UNMEASURABLE si le gross ou une composante déductible est absente/non finie.
    """
    par_nom: dict[str, set[bool]] = {}
    for c in composantes:
        par_nom.setdefault(str(c.name), set()).add(bool(c.included_in_price))
    double = tuple(sorted(n for n, modes in par_nom.items() if modes == {True, False}))

    explicites = [c for c in composantes if not c.included_in_price]
    noms_explicites = tuple(str(c.name) for c in explicites)

    g = _num(gross_edge_bps)
    if g is None or any(_num(c.bps) is None for c in explicites):
        net = None
    else:
        net = round(g - sum(float(c.bps) for c in explicites), 6)

    if double:
        verdict = "DOUBLE_COMPTE"
    elif net is None:
        verdict = "UNMEASURABLE"
    else:
        verdict = "OK"
    return VerificationCouts(net_bps=net, double_comptes=double, verdict=verdict,
                             deductions_explicites=noms_explicites)


__all__ = [
    "SCHEMA_VERSION", "MEASURED", "ASSUMED", "UNMEASURABLE",
    "taxonomie_latence", "ComposanteCout", "VerificationCouts", "verifier_convention_couts",
]
