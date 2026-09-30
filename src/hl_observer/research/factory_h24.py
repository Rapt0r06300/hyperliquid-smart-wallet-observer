"""CHANTIER #70 — FACTORY H24 : DISCOVERY → FREEZE → OOS → FORWARD (débloqué par les captures #64/#65).

Chaque nouvelle capture produit automatiquement des trials, mais SOUS DISCIPLINE : on ne cherche plus des
indicateurs au hasard, on cherche des CONFIGURATIONS dont LCB(net) > 0 après coûts, prouvées HORS
DÉCOUVERTE. Pipeline par cycle :
  * DISCOVERY  — un trial promu (verdict promouvable ET net>0) voit sa config SCELLÉE (forward_frozen) ;
  * FREEZE     — la config est immuable ; aucun retune (garanti par ForwardFrozen) ;
  * OOS/FORWARD— sur les cycles suivants, la config scellée est seulement MESURÉE (net observé), jamais
                 re-choisie ; un candidat n'est CONFIRMÉ que si LCB(net forward) > 0 sur assez d'observations.

`produire_trials(cycle)` est injecté (en prod : run_factory.run_all(...)["rows"]). Sans cycle → rien scellé.
0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from hl_observer.research.forward_frozen import ForwardFrozen

_PROMOUVABLES = {"CANDIDAT", "ANTICIPATEUR_A_FORWARD", "OOS_POSITIF_A_FORWARD", "FORWARD_REQUIS"}


def _lcb(xs: Sequence[float], *, z: float = 1.64) -> float | None:
    """Borne basse de confiance (normale, unilatérale ~95%) du net forward. None si < 2 observations."""
    v = [float(x) for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    var = sum((x - m) ** 2 for x in v) / (len(v) - 1)
    return round(m - z * (var ** 0.5) / (len(v) ** 0.5), 4)


def _cid(row: Mapping[str, Any]) -> str:
    return str(row.get("_famille") or row.get("config_hash") or row.get("idea"))


def lancer_h24(cycles: Sequence[Any], produire_trials: Callable[[Any], Sequence[Mapping[str, Any]]], *,
               forward_path: str | None = None, promouvables: set[str] | None = None,
               lcb_min: float = 0.0, min_forward: int = 2) -> dict[str, Any]:
    """Rejoue les cycles sous discipline DISCOVERY→FREEZE→OOS→FORWARD et confirme les configs dont
    LCB(net forward) > `lcb_min` sur >= `min_forward` observations."""
    promouvables = promouvables or _PROMOUVABLES
    ff = ForwardFrozen(forward_path)
    frozen_cycle: dict[str, int] = {}
    forward_nets: dict[str, list[float]] = {}
    for i, cyc in enumerate(cycles):
        rows = produire_trials(cyc) or []
        deja = set(ff.candidats())
        for r in rows:
            cid = _cid(r)
            net = r.get("net_bps")
            if cid in deja:                                   # SCELLÉ -> observation OOS/FORWARD (jamais retune)
                if isinstance(net, (int, float)):
                    ff.observer(cid, {"net_bps": net, "cycle": i, "verdict": r.get("verdict")})
                    forward_nets.setdefault(cid, []).append(float(net))
            elif r.get("verdict") in promouvables and isinstance(net, (int, float)) and net > 0:
                ff.promouvoir(cid, {"idea": r.get("idea"), "config_frozen": r.get("config_frozen"),
                                    "famille": r.get("_famille")})   # DISCOVERY -> FREEZE
                frozen_cycle[cid] = i
    resultats: dict[str, Any] = {}
    for cid in ff.candidats():
        nets = forward_nets.get(cid, [])
        lcb = _lcb(nets)
        confirme = bool(len(nets) >= min_forward and lcb is not None and lcb > lcb_min)
        stade = ("FORWARD_CONFIRME" if confirme else
                 ("FORWARD_INSUFFISANT" if nets else "FREEZE_SANS_FORWARD"))
        resultats[cid] = {"frozen_cycle": frozen_cycle.get(cid), "n_forward": len(nets),
                          "net_moyen_forward_bps": (round(sum(nets) / len(nets), 4) if nets else None),
                          "lcb_forward_bps": lcb, "confirme": confirme, "stade": stade}
    n_conf = sum(1 for v in resultats.values() if v["confirme"])
    return {"n_cycles": len(cycles), "n_scelles": len(ff.candidats()), "n_confirmes": n_conf,
            "candidats": resultats, "real_execution": False}


def produire_via_run_all(registry_path: str, *, fee_bps: float = 9.0) -> Callable[[str], list[dict[str, Any]]]:
    """Fabrique un `produire_trials` réel branché sur run_factory.run_all (une capture = un data_dir)."""
    from hl_observer.research import run_factory as _rf

    def _prod(data_dir: str) -> list[dict[str, Any]]:
        return _rf.run_all(data_dir=data_dir, registry_path=registry_path, fee_bps=fee_bps)["rows"]

    return _prod


__all__ = ["lancer_h24", "produire_via_run_all"]
