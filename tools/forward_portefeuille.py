"""FORWARD PAPER = VRAI PORTEFEUILLE À CAPITAL PARTAGÉ (Flo 26/07, PT-5 + FX-6).

Au lieu d'une médiane de net par candidat, on rejoue le forward comme un portefeuille unique : les signaux de
TOUS les candidats figés se disputent le MÊME capital, dans l'ORDRE CHRONOLOGIQUE. Chaque signal = OPEN à
prix exécutable (ask long / bid short) puis CLOSE au prix exécutable futur (bid long / ask short) à l'horizon.
Les positions coexistent (expositions simultanées) tant que le capital le permet ; le spread est payé dans les
prix, les autres coûts (fees, slippage, impact, funding, latence) sont appliqués UNE fois à l'ouverture.

FX-6 : (1) un signal n'est retenu que s'il est status OK **ET** promotable **ET** exit_source == FWD_BOOK
(jamais un APPROXIMATE) ; (2) la limite par candidat est CONFIGURABLE (None = sans limite) ; (3) les sorties
planifiées (closes) sont PERSISTÉES sur disque (position_id/exit_ts/horizon/candidat/règle) et REPRISES après
crash automatiquement ; (4) on ne ferme JAMAIS une position dont l'échéance réelle n'est pas encore arrivée
simplement parce qu'un appel de campagne se termine. Produit un ledger d'événements réconciliable. 0 ordre réel.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _signaux(geles, corpus_fwd, *, filtrer, evaluer, max_par_candidat=None, stop_event=None):
    """Construit les signaux EXÉCUTABLES et PROMOUVABLES (status OK + promotable + exit_source FWD_BOOK) pour
    tous les candidats figés. `max_par_candidat=None` -> aucune limite (FX-6). Un APPROXIMATE n'entre jamais."""
    sigs = []
    for c in geles:
        if stop_event is not None and stop_event.is_set():
            break
        sub = filtrer(corpus_fwd, coin=c.get("coin"), regime=c.get("regime"))
        n = 0
        for ep in sub:
            o = evaluer(ep, sens=c["direction"], horizon_ms=c["horizon_ms"])
            if o.get("status") != "OK" or not o.get("promotable") or o.get("exit_source") != "FWD_BOOK":
                continue                                     # FX-6 : seuls les PROMOUVABLES (FWD_BOOK) tradent
            sigs.append({"trial_id": c["trial_id"], "coin": c["coin"], "sens": c["direction"],
                         "horizon_ms": c["horizon_ms"], "entry_ts": o["entry_ts"], "exit_ts": o["exit_ts"],
                         "entry_px": o["entry_px"], "exit_px": o["exit_px"],
                         "couts": {"fees_bps": o.get("fees_bps"), "slippage_bps": o.get("slippage_bps"),
                                   "impact_bps": o.get("impact_bps"), "funding_bps": o.get("funding_bps"),
                                   "latency_bps": o.get("latency_bps")}})
            n += 1
            if max_par_candidat is not None and n >= max_par_candidat:
                break
    sigs.sort(key=lambda s: (s["entry_ts"], s["trial_id"]))
    return sigs


class SortiesEnAttente:
    """Sorties (closes) planifiées PERSISTÉES (FX-6). Chaque entrée : position_id, exit_ts, exit_px, horizon_ms,
    candidat, regle. Elles SURVIVENT au crash (fichier JSON atomique) et sont REPRISES automatiquement : au
    prochain passage, toute sortie dont l'échéance (exit_ts) est atteinte est rejouée, sans intervention."""

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)
        self.items = self._charger()

    def _charger(self) -> list:
        try:
            return json.loads(self.chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _sauver(self):
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.chemin.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.chemin)

    def ajouter(self, **kw):
        self.items.append(kw)
        self._sauver()

    def retirer(self, position_ids):
        pids = set(position_ids)
        if not pids:
            return
        self.items = [x for x in self.items if x.get("position_id") not in pids]
        self._sauver()


def simuler(geles, corpus_fwd, *, filtrer, evaluer, capital: float = 1000.0, notional_par_trade: float = 100.0,
            levier: float = 3.0, stop_event=None, portefeuille=None, max_par_candidat=None, pending_path=None,
            maintenant_ms=None, fermer_tout_a_la_fin: bool = False) -> dict:
    """Rejoue le forward à capital PARTAGÉ. `portefeuille` = le portefeuille GLOBAL persistant du run (AF-P3) s'il
    est fourni, sinon un portefeuille paper local. `pending_path` (fichier JSON) PERSISTE les sorties planifiées
    et permet la REPRISE après crash. Par défaut on NE ferme PAS les positions dont l'échéance n'est pas atteinte
    (elles restent ouvertes + persistées). `maintenant_ms` fixe l'instant courant (par défaut = dernier entry_ts
    observé). `fermer_tout_a_la_fin=True` ne sert qu'à un cas de test explicite, jamais au flux normal."""
    if portefeuille is not None:
        pf = portefeuille
    else:
        from portefeuille_paper import PortefeuillePaper
        pf = PortefeuillePaper(capital, levier=levier)
    store = SortiesEnAttente(pending_path) if pending_path is not None else None

    pending = []                                              # (exit_ts, position_id, exit_px)
    if store is not None:                                     # REPRISE : recharger les sorties persistées (post-crash)
        for x in store.items:
            try:
                pending.append((float(x["exit_ts"]), x["position_id"], float(x["exit_px"])))
            except (KeyError, TypeError, ValueError):
                continue

    sigs = _signaux(geles, corpus_fwd, filtrer=filtrer, evaluer=evaluer,
                    max_par_candidat=max_par_candidat, stop_event=stop_event)
    n_ouverts = n_refuses = 0

    def _fermer_du(ts):
        nonlocal pending
        prets = [x for x in pending if x[0] <= ts]
        fermes = []
        for exit_ts, pid, exit_px in sorted(prets):
            pf.fermer(pid, prix=exit_px, ts_ms=exit_ts)      # coûts déjà payés à l'ouverture
            fermes.append(pid)
        pending = [x for x in pending if x[0] > ts]
        if store is not None and fermes:
            store.retirer(fermes)                            # les sorties consommées quittent le disque

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
            if store is not None:                            # PERSISTE la sortie planifiée (survit au crash)
                store.ajouter(position_id=pid, exit_ts=s["exit_ts"], exit_px=s["exit_px"],
                              horizon_ms=s.get("horizon_ms"), candidat=s["trial_id"], regle="HORIZON")

    # échéances RÉELLEMENT atteintes : on ne ferme que les sorties mûres (exit_ts <= maintenant). Les positions
    # dont l'échéance n'est pas encore arrivée restent OUVERTES et PERSISTÉES (reprises au prochain cycle/redémarrage).
    if fermer_tout_a_la_fin:
        maintenant = float("inf")
    elif maintenant_ms is not None:
        maintenant = float(maintenant_ms)
    else:
        maintenant = max((s["entry_ts"] for s in sigs), default=0.0)   # dernier instant de marché observé
    _fermer_du(maintenant)

    return {"portefeuille": pf, "n_signaux": len(sigs), "n_ouverts": n_ouverts, "n_refuses": n_refuses,
            "n_sorties_en_attente": len(pending), "reconciliation": pf.reconcilier()}


__all__ = ["simuler", "SortiesEnAttente"]
