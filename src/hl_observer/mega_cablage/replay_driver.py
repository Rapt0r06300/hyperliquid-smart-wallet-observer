"""[CABLAGE replay] DRIVER de replay massif + découpe IS / OOS / FORWARD. On rejoue un flux d'événements
ordonné dans le temps à travers MegaCablage et on le découpe en segments temporels :
  - IS (in-sample)   : la partie ancienne, pour observer le comportement ;
  - OOS (out-of-sample) : la partie suivante, JAMAIS utilisée pour régler quoi que ce soit ;
  - FORWARD          : la tranche la plus récente, validation « en avant ».
Chaque segment est rejoué sur un pipeline NEUF et on compare les ROI. Honnêteté dure : ce driver ne FABRIQUE
aucun résultat — un run sur données synthétiques est labellisé comme tel (`SYNTHETIQUE_DEMO`), et le run massif
RÉEL se lance sur les logs enregistrés (48h ticks coin+mid+book) via `python -m hl_observer.mega_cablage
--from-logs <dir>` ou `driver_depuis_logs(<dir>)`. Un ROI n'est jamais promis. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.mega_cablage.pipeline import MegaCablage
from hl_observer.mega_cablage.runner import _EquityMap, charger_evenements_logs

UNMEASURABLE = "UNMEASURABLE"


def separer_temporel(evenements: list[dict[str, Any]], *, fractions: tuple[float, ...] = (0.6, 0.2, 0.2),
                     labels: tuple[str, ...] = ("IS", "OOS", "FORWARD")) -> dict[str, list]:
    """Trie par ts_ms puis découpe par fractions de COMPTE (déterministe). Le reste va au dernier segment."""
    ordered = sorted(evenements, key=lambda e: e.get("ts_ms") or 0)
    n = len(ordered)
    segments: dict[str, list] = {}
    start = 0
    for frac, lab in zip(fractions, labels):
        end = start + int(round(frac * n))
        segments[lab] = ordered[start:end]
        start = end
    if start < n and labels:
        segments[labels[-1]] = segments.get(labels[-1], []) + ordered[start:]
    for lab in labels:
        segments.setdefault(lab, [])
    return segments


def rejouer_segment(evenements: list[dict[str, Any]], *, notre_equity: float = 1000.0,
                    notional_max: float = 500.0, fee_bps: float = 4.5,
                    leader_equity_defaut: float | None = None) -> dict[str, Any]:
    """Rejoue un segment sur un pipeline NEUF. Rend {ticks, events, equity, roi, realized, fees, reconcilie,
    fills, rejets}. ROI = (equity − equity_depart)/equity_depart."""
    pipe = MegaCablage(notre_equity=notre_equity, notional_max=notional_max, fee_bps=fee_bps)
    if evenements:
        pipe.traiter_replay(list(evenements),
                            leader_equity_par_vault=_EquityMap({}, leader_equity_defaut))
    r = pipe.resume()
    pnl = r["pnl"]
    n_fills = sum(1 for t in pipe.trace for f in t["fills"] if f.get("execute"))
    n_rejets = sum(len(t["rejets"]) for t in pipe.trace)
    roi = round((pnl["equity"] - notre_equity) / notre_equity, 8) if notre_equity > 0 else UNMEASURABLE
    return {"ticks": r["ticks"], "events": len(evenements), "equity": pnl["equity"], "roi": roi,
            "realized": pnl["realized"], "fees": pnl["fees"], "reconcilie": bool(pnl["reconcilie"]),
            "fills": n_fills, "rejets": n_rejets}


def rejouer_is_oos_forward(evenements: list[dict[str, Any]], *, fractions: tuple[float, ...] = (0.6, 0.2, 0.2),
                           source: str = "INCONNU", notre_equity: float = 1000.0,
                           notional_max: float = 500.0, fee_bps: float = 4.5,
                           leader_equity_defaut: float | None = None) -> dict[str, Any]:
    """Découpe IS/OOS/FORWARD et rejoue chaque segment isolément. Verdict : OOS et FORWARD tiennent-ils (ROI ≥ 0
    ET réconciliés) ? La note distingue un run RÉEL d'un run SYNTHETIQUE_DEMO — aucun ROI promis."""
    segs = separer_temporel(evenements, fractions=fractions)
    kw = {"notre_equity": notre_equity, "notional_max": notional_max, "fee_bps": fee_bps,
          "leader_equity_defaut": leader_equity_defaut}
    rapports = {lab: rejouer_segment(evs, **kw) for lab, evs in segs.items()}

    def _roi(lab: str) -> Any:
        return rapports.get(lab, {}).get("roi")

    oos, fwd = _roi("OOS"), _roi("FORWARD")
    tenue = all(isinstance(x, (int, float)) and x >= 0 for x in (oos, fwd))
    note = "SYNTHETIQUE_DEMO" if str(source).upper().startswith("SYNTH") else "REEL"
    return {"source": source, "segments": rapports,
            "verdict": {"is_roi": _roi("IS"), "oos_roi": oos, "forward_roi": fwd,
                        "oos_forward_tiennent": tenue, "note": note},
            "reconcilie_partout": all(r["reconcilie"] for r in rapports.values())}


def driver_depuis_logs(chemin: Any, *, source: str = "REEL_LOGS", **kwargs: Any) -> dict[str, Any]:
    """Charge un flux d'événements depuis des logs jsonl (le run massif RÉEL) puis rejoue IS/OOS/FORWARD. Logs
    absents/vides → segments vides, réconciliation triviale + note honnête (aucun résultat fabriqué)."""
    evenements = charger_evenements_logs(chemin)
    resultat = rejouer_is_oos_forward(evenements, source=source, **kwargs)
    if not evenements:
        resultat["verdict"]["note"] = "AUCUN_EVENEMENT_DANS_LOGS"
    return resultat


__all__ = ["separer_temporel", "rejouer_segment", "rejouer_is_oos_forward", "driver_depuis_logs",
           "UNMEASURABLE"]
