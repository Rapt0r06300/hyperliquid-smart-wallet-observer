"""[CABLAGE étage G] ORCHESTRATEUR : thread le CHEMIN RÉEL de bout en bout, par TICK (tous les événements d'un
même ts_ms) —

    admission → copie → (hedge cross-venue) → netting/routing → risque → fill → ledger → PnL

C'est ici que les pépites 201-300, jusque-là isolées, se composent réellement : deux leaders sur le même coin
dans le même tick sont NETTÉS en un seul ordre ; un événement au carnet croisé est REJETÉ à l'admission
(NO_TRADE) ; un candidat qui dépasse le plafond est REFUSÉ au risque ; un carnet trop mince donne un MISSED_FILL.
Le PnL final vient du VRAI ledger d'événements et se réconcilie. Une intention sur une venue de hedge non-paper
(ex. BINANCE) est TRACÉE mais pas exécutée en paper ici. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from hl_observer.mega_cablage.event_admission import admettre
from hl_observer.mega_cablage.copy_stage import intent_copie
from hl_observer.mega_cablage.cross_venue_stage import intent_hedge
from hl_observer.mega_cablage.netting_routing_stage import netter_et_router
from hl_observer.mega_cablage.risk_stage import filtrer_risque
from hl_observer.mega_cablage.fill_ledger_stage import ExecuteurPaper


class MegaCablage:
    """Orchestrateur stateful. Détient l'ExecuteurPaper (donc le PaperLedger) et la trace par tick. Le sizing de
    copie utilise l'equity VIVANTE du ledger (pas une valeur figée)."""

    def __init__(self, *, notre_equity: float = 1000.0, notional_max: float = 500.0, fee_bps: float = 4.5,
                 venue: str = "HYPERLIQUID", min_fill_ratio: float = 0.85, verifier_unite: bool = True,
                 drawdown_gate: Any = None, verrou: Any = None) -> None:
        self.notional_max = float(notional_max)
        self.venue = str(venue).upper()
        self.verifier_unite = bool(verifier_unite)
        self.drawdown_gate = drawdown_gate
        self.verrou = verrou
        self.executeur = ExecuteurPaper(starting_balance_usdc=notre_equity, fee_bps=fee_bps,
                                        min_fill_ratio=min_fill_ratio)
        self.trace: list[dict[str, Any]] = []

    def traiter_tick(self, evenements: list[dict[str, Any]], *, leader_equity_par_vault: dict[str, Any],
                     routes_par_cle: dict[str, list] | None = None,
                     marks: dict[str, float] | None = None) -> dict[str, Any]:
        """Traite tous les événements d'un tick. Dérive prix/carnets des événements eux-mêmes. Retourne la trace
        du tick (rejets d'admission, self-trade, candidats, fills, PnL courant)."""
        if not evenements:
            return {"ts_ms": None, "rejets": [], "fills": [], "pnl": self.executeur.pnl()}
        ts_ms = evenements[0].get("ts_ms")
        equity_courante = self.executeur.ledger.equity_usdc
        prix_par_coin: dict[str, Any] = {}
        books_par_coin: dict[str, Any] = {}
        intents: list[dict[str, Any]] = []
        rejets: list[dict[str, Any]] = []
        for ev in evenements:
            coin = str(ev.get("coin", "")).upper()
            prix_par_coin[coin] = ev.get("mid", ev.get("px"))
            if isinstance(ev.get("book"), dict):
                books_par_coin[coin] = ev["book"]
            adm = admettre(ev, verifier_unite=self.verifier_unite)
            if not adm.get("admis"):
                rejets.append({"coin": coin, "raison": adm.get("raison")})
                continue
            leader_equity = leader_equity_par_vault.get(ev.get("vault"))
            cp = intent_copie(ev, notre_equity=equity_courante, leader_equity=leader_equity, venue=self.venue)
            if cp.get("refuse"):
                rejets.append({"coin": coin, "raison": "COPY_%s" % cp.get("raison")})
                continue
            intents.append(cp["intent"])
            edge = ev.get("cross_venue_edge_bps")
            if edge is not None:
                h = intent_hedge(coin=coin, notional_copie_signe=cp["intent"]["montant_signe"],
                                 edge_cross_venue_bps=edge)
                if h.get("hedge"):
                    intents.append(h["hedge"])
        nr = netter_et_router(intents, prix_par_coin=prix_par_coin, routes_par_cle=routes_par_cle)
        fills: list[dict[str, Any]] = []
        for c in nr["candidats"]:
            cand = c.get("candidat")
            if not cand or not cand.get("valide"):
                fills.append({"cle": c["cle"], "execute": False, "raison": c.get("raison")})
                continue
            if c.get("venue") != self.venue:
                fills.append({"cle": c["cle"], "execute": False, "raison": "VENUE_NON_PAPER"})
                continue
            rk = filtrer_risque(cand, notional_max=self.notional_max, coin=c["coin"], now_ms=ts_ms,
                                drawdown_gate=self.drawdown_gate, verrou=self.verrou,
                                equity=self.executeur.ledger.equity_usdc)
            if not rk.get("autorise"):
                fills.append({"cle": c["cle"], "execute": False, "raison": rk.get("raison")})
                continue
            res = self.executeur.executer(cand, book=books_par_coin.get(c["coin"], {}),
                                          mid=prix_par_coin.get(c["coin"]), ts_ms=ts_ms)
            fills.append({"cle": c["cle"], "execute": res.get("execute"), "action": res.get("action"),
                          "raison": res.get("raison"), "fill_price": res.get("fill_price"),
                          "filled_notional": res.get("filled_notional")})
        self.executeur.marquer(marks or {k: v for k, v in prix_par_coin.items()
                                         if isinstance(v, (int, float))}, ts_ms=ts_ms)
        tick = {"ts_ms": ts_ms, "rejets": rejets, "self_trade": nr["self_trade"]["self_trade"],
                "n_candidats": len(nr["candidats"]), "fills": fills, "pnl": self.executeur.pnl()}
        self.trace.append(tick)
        return tick

    def traiter_replay(self, flux: list[dict[str, Any]], *, leader_equity_par_vault: dict[str, Any],
                       routes_par_cle: dict[str, list] | None = None) -> dict[str, Any]:
        """Convenience replay : groupe un flux plat d'événements par ts_ms (ordre stable) et traite chaque tick."""
        groupes: "OrderedDict[Any, list]" = OrderedDict()
        for ev in flux:
            groupes.setdefault(ev.get("ts_ms"), []).append(ev)
        for _, evs in groupes.items():
            self.traiter_tick(evs, leader_equity_par_vault=leader_equity_par_vault,
                              routes_par_cle=routes_par_cle)
        return self.resume()

    def resume(self) -> dict[str, Any]:
        return {"pnl": self.executeur.pnl(), "ticks": len(self.trace),
                "snapshot": self.executeur.ledger.snapshot()}


__all__ = ["MegaCablage"]
