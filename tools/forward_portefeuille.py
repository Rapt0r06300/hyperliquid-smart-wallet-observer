"""FORWARD PAPER = VRAI PORTEFEUILLE À CAPITAL PARTAGÉ (Flo 26/07, PT-5 câblé).

Au lieu d'une médiane de net par candidat, on rejoue le forward comme un portefeuille unique : les signaux de
TOUS les candidats figés se disputent le MÊME capital, dans l'ORDRE CHRONOLOGIQUE. Chaque signal = OPEN à
prix exécutable (ask long / bid short) puis CLOSE au prix exécutable futur (bid long / ask short) à l'horizon.
Les positions coexistent (expositions simultanées) tant que le capital le permet ; le spread est payé dans les
prix, les autres coûts (fees, slippage, impact, funding, latence) sont appliqués UNE fois à l'ouverture.
Produit un ledger d'événements réconciliable. 0 ordre réel, paper-only.
"""
from __future__ import annotations

from pathlib import Path


def _signaux(geles, corpus_fwd, *, filtrer, evaluer, max_par_candidat=400, stop_event=None):
    """Construit les signaux exécutables (status OK) pour tous les candidats figés."""
    sigs = []
    for c in geles:
        if stop_event is not None and stop_event.is_set():
            break
        sub = filtrer(corpus_fwd, coin=c.get("coin"), regime=c.get("regime"))
        n = 0
        for ep in sub:
            o = evaluer(ep, sens=c["direction"], horizon_ms=c["horizon_ms"])
            if o.get("status") != "OK":
                continue
            sigs.append({"trial_id": c["trial_id"], "coin": c["coin"], "sens": c["direction"],
                         "entry_ts": o["entry_ts"], "exit_ts": o["exit_ts"],
                         "entry_px": o["entry_px"], "exit_px": o["exit_px"],
                         "couts": {"fees_bps": o.get("fees_bps"), "slippage_bps": o.get("slippage_bps"),
                                   "impact_bps": o.get("impact_bps"), "funding_bps": o.get("funding_bps"),
                                   "latency_bps": o.get("latency_bps")}})
            n += 1
            if n >= max_par_candidat:
                break
    sigs.sort(key=lambda s: (s["entry_ts"], s["trial_id"]))
    return sigs


def simuler(geles, corpus_fwd, *, filtrer, evaluer, capital: float = 1000.0, notional_par_trade: float = 100.0,
            levier: float = 3.0, stop_event=None) -> dict:
    """Rejoue le forward à capital PARTAGÉ. Rend {portefeuille, n_signaux, n_ouverts, n_refuses, reconciliation}."""
    from portefeuille_paper import PortefeuillePaper
    pf = PortefeuillePaper(capital, levier=levier)
    sigs = _signaux(geles, corpus_fwd, filtrer=filtrer, evaluer=evaluer, stop_event=stop_event)
    pending = []                                              # (exit_ts, position_id, exit_px)
    n_ouverts = n_refuses = 0

    def _fermer_du(ts):
        nonlocal pending
        prets = [x for x in pending if x[0] <= ts]
        for exit_ts, pid, exit_px in sorted(prets):
            pf.fermer(pid, prix=exit_px, ts_ms=exit_ts)      # coûts déjà payés à l'ouverture
        pending = [x for x in pending if x[0] > ts]

    for s in sigs:
        if stop_event is not None and stop_event.is_set():
            break
        _fermer_du(s["entry_ts"])                            # libère le capital des positions arrivées à échéance
        pid = "%s:%s" % (s["trial_id"], s["entry_ts"])
        r = pf.ouvrir(pid, coin=s["coin"], sens=s["sens"], notional=notional_par_trade,
                      prix=s["entry_px"], ts_ms=s["entry_ts"], couts=s["couts"])
        if r.get("refus"):
            n_refuses += 1
        else:
            n_ouverts += 1
            pending.append((s["exit_ts"], pid, s["exit_px"]))
    for exit_ts, pid, exit_px in sorted(pending):            # clôture des positions restantes
        pf.fermer(pid, prix=exit_px, ts_ms=exit_ts)
    return {"portefeuille": pf, "n_signaux": len(sigs), "n_ouverts": n_ouverts, "n_refuses": n_refuses,
            "reconciliation": pf.reconcilier()}


__all__ = ["simuler"]
