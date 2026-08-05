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
from hl_observer.mega_cablage.runner import _EquityMap, charger_bundles_logs
from hl_observer.mega_cablage.feed_adapter import evenements_depuis_bundles

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


def episodes_indivisibles(evenements: list[dict[str, Any]], *, gap_ms: int = 3_600_000) -> list[list]:
    """Regroupe les événements en ÉPISODES INDIVISIBLES (item 14) — l'unité qui ne doit JAMAIS être coupée
    entre IS/OOS/FORWARD : un `episode_id`/`metaorder_id` explicite quand il existe, sinon un run CONTIGU de
    même (vault, coin, direction) sans trou temporel > `gap_ms`. Un flip de direction, un métaordre/TWAP,
    un épisode Lead-Lag ou cross-venue complet forme donc UN épisode. Rend la liste d'épisodes (chacun trié
    par ts)."""
    ordered = sorted(evenements, key=lambda e: e.get("ts_ms") or 0)

    def _cle(ev: dict[str, Any]):
        eid = ev.get("episode_id") or ev.get("metaorder_id") or ev.get("episode")
        if eid is not None:
            return ("id", eid)
        signe = 1 if (ev.get("signe") or 0) >= 0 else -1
        return ("run", ev.get("vault"), ev.get("coin"), signe)

    episodes: list[list] = []
    courant: list = []
    prev_cle = None
    prev_ts = None
    for ev in ordered:
        k = _cle(ev)
        ts = ev.get("ts_ms") or 0
        rupture = (k != prev_cle) or (prev_ts is not None and (ts - prev_ts) > gap_ms)
        if courant and rupture:
            episodes.append(courant)
            courant = []
        courant.append(ev)
        prev_cle, prev_ts = k, ts
    if courant:
        episodes.append(courant)
    return episodes


def separer_par_episodes(evenements: list[dict[str, Any]], *, fractions: tuple[float, ...] = (0.6, 0.2, 0.2),
                         labels: tuple[str, ...] = ("IS", "OOS", "FORWARD"),
                         gap_ms: int = 3_600_000) -> dict[str, list]:
    """Découpe IS/OOS/FORWARD par ÉPISODES INDIVISIBLES (item 14) : aucun épisode ne traverse deux segments.
    Les épisodes sont ordonnés par ts de début et affectés ENTIERS aux segments pour approcher les fractions
    par compte d'événements. Un run interrompu (position à cheval) est donc impossible par construction."""
    eps = episodes_indivisibles(evenements, gap_ms=gap_ms)
    n = sum(len(e) for e in eps)
    segments: dict[str, list] = {lab: [] for lab in labels}
    if n == 0:
        return segments
    cibles: list[float] = []
    acc = 0.0
    for frac in fractions:
        acc += frac
        cibles.append(acc * n)
    seg_idx = 0
    compte = 0
    for ep in eps:
        segments[labels[seg_idx]].extend(ep)          # l'épisode ENTIER va au segment courant
        compte += len(ep)
        while seg_idx < len(labels) - 1 and compte >= cibles[seg_idx]:
            seg_idx += 1
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
    """Run massif RÉEL : charge les logs jsonl → bundles → feed_adapter (MÊME chemin que le runner) → IS/OOS/
    FORWARD. Logs absents/vides → segments vides + note honnête (aucun résultat fabriqué)."""
    evenements = evenements_depuis_bundles(charger_bundles_logs(chemin))
    resultat = rejouer_is_oos_forward(evenements, source=source, **kwargs)
    if not evenements:
        resultat["verdict"]["note"] = "AUCUN_EVENEMENT_DANS_LOGS"
    return resultat


__all__ = ["separer_temporel", "rejouer_segment", "rejouer_is_oos_forward", "driver_depuis_logs",
           "UNMEASURABLE"]
