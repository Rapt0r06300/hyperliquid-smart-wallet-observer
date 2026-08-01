"""[CABLAGE étage G] ORCHESTRATEUR : thread le CHEMIN RÉEL de bout en bout, par TICK (tous les événements d'un
même ts_ms) —

    admission → copie → (cross-venue 2 jambes | netting/routing) → risque → fill → PaperLedger → PnL

C'est ici que les pépites 201-300, jusque-là isolées, se composent réellement, sur UN SEUL ledger réconcilié :
 - deux leaders sur le même coin dans le même tick sont NETTÉS en un seul ordre single-venue ;
 - un événement portant un `cross_venue` complet (edge + carnet hedge) est routé vers cross_venue_paper_stage :
   les DEUX jambes (HYPERLIQUID + BINANCE) sont EXÉCUTÉES et comptabilisées en paper dans le MÊME PaperLedger
   (positions COIN@VENUE distinctes → aucun double comptage avec les positions single-venue COIN:SIDE) ;
 - un carnet croisé est REJETÉ à l'admission (NO_TRADE) ; un candidat hors plafond est REFUSÉ au risque ;
 - un carnet trop mince → MISSED_FILL ; un carnet/mid ABSENT → MORE_DATA (jamais un fill fabriqué) ;
 - un edge cross-venue signalé SANS carnet hedge → note CROSS_VENUE_MORE_DATA (pas de hedge inventé).
Le PnL final vient du VRAI ledger d'événements et se réconcilie (equity = start + realized + unrealized − fees +
funding). 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from hl_observer.mega_cablage.event_admission import admettre
from hl_observer.mega_cablage.copy_stage import intent_copie
from hl_observer.mega_cablage.netting_routing_stage import netter_et_router
from hl_observer.mega_cablage.risk_stage import filtrer_risque
from hl_observer.mega_cablage.fill_ledger_stage import ExecuteurPaper
from hl_observer.mega_cablage.cross_venue_paper_stage import executer_paire_cross_venue


class MegaCablage:
    """Orchestrateur stateful. Détient l'ExecuteurPaper (donc le PaperLedger partagé) et la trace par tick. Le
    sizing de copie utilise l'equity VIVANTE du ledger (pas une valeur figée). cross_venue_paper active
    l'exécution paper des deux jambes cross-venue (par défaut True)."""

    def __init__(self, *, notre_equity: float = 1000.0, notional_max: float = 500.0, fee_bps: float = 4.5,
                 venue: str = "HYPERLIQUID", min_fill_ratio: float = 0.85, verifier_unite: bool = True,
                 drawdown_gate: Any = None, verrou: Any = None, cross_venue_paper: bool = True,
                 seuil_edge_cross_venue_bps: float = 1.0) -> None:
        self.notional_max = float(notional_max)
        self.venue = str(venue).upper()
        self.verifier_unite = bool(verifier_unite)
        self.drawdown_gate = drawdown_gate
        self.verrou = verrou
        self.cross_venue_paper = bool(cross_venue_paper)
        self.seuil_edge_cv = float(seuil_edge_cross_venue_bps)
        self.executeur = ExecuteurPaper(starting_balance_usdc=notre_equity, fee_bps=fee_bps,
                                        min_fill_ratio=min_fill_ratio)
        self.trace: list[dict[str, Any]] = []

    def _executer_cross_venue(self, job: dict[str, Any], *, ts_ms: Any) -> dict[str, Any]:
        """Exécute les deux jambes dans le MÊME ledger via cross_venue_paper_stage. Carnet invalide / edge sous
        seuil → CROSS_VENUE_MORE_DATA (pas de hedge fabriqué)."""
        cv = job["cv"]
        coin = job["coin"]
        edge = cv.get("edge_bps")
        if not isinstance(edge, (int, float)) or edge < self.seuil_edge_cv:
            return {"coin": coin, "execute": False, "raison": "CROSS_VENUE_EDGE_SOUS_SEUIL"}
        action1 = "BUY" if job["side"] == "BUY" else "SELL"
        action2 = "SELL" if action1 == "BUY" else "BUY"
        try:
            r = executer_paire_cross_venue(
                coin=coin, venue1=self.venue, venue2=str(cv.get("venue_hedge", "BINANCE")).upper(),
                action1=action1, action2=action2, notional_usdc=float(job["notional"]), ts_ms=int(ts_ms),
                latences_ms=tuple(cv.get("latences_ms") or (10.0, 20.0, 30.0, 40.0, 50.0)),
                carnet1_entree=job["book_hl"], carnet2=cv["carnet_hedge"],
                carnet1_unwind=cv.get("carnet_unwind") or job["book_hl"],
                ledger=self.executeur.ledger)
        except (ValueError, KeyError, TypeError) as exc:            # carnet absent/croisé, latences invalides…
            return {"coin": coin, "execute": False, "raison": "CROSS_VENUE_MORE_DATA", "detail": str(exc)}
        return {"coin": coin, "execute": True, "action": "CROSS_VENUE_2_JAMBES",
                "matched_notional": r["matched_notional"], "paired_edge_usdc": r["paired_edge_usdc"],
                "positions_ledger": len(r["positions"]), "chaine_ok": r["chaine_ok"]}

    def traiter_tick(self, evenements: list[dict[str, Any]], *, leader_equity_par_vault: dict[str, Any],
                     routes_par_cle: dict[str, list] | None = None,
                     marks: dict[str, float] | None = None) -> dict[str, Any]:
        """Traite tous les événements d'un tick. Dérive prix/carnets des événements. Route chaque événement soit
        vers le netting single-venue, soit (cross_venue complet) vers l'exécution 2 jambes. Retourne la trace."""
        if not evenements:
            return {"ts_ms": None, "rejets": [], "notes": [], "fills": [], "cross_venue": [],
                    "n_candidats": 0, "self_trade": False, "pnl": self.executeur.pnl()}
        ts_ms = evenements[0].get("ts_ms")
        equity_courante = self.executeur.ledger.equity_usdc
        prix_par_coin: dict[str, Any] = {}
        books_par_coin: dict[str, Any] = {}
        intents: list[dict[str, Any]] = []
        rejets: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        jobs_cv: list[dict[str, Any]] = []
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
            cv = ev.get("cross_venue")
            if self.cross_venue_paper and isinstance(cv, dict) and cv.get("carnet_hedge") \
                    and isinstance(ev.get("book"), dict):
                # La jambe de copie EST la jambe 1 (venue primaire) — on ne l'ajoute PAS au netting (0 double compte)
                jobs_cv.append({"coin": coin, "notional": cp["notional"], "side": cp["side"],
                                "book_hl": ev["book"], "cv": cv})
                continue
            intents.append(cp["intent"])
            if ev.get("cross_venue_edge_bps") is not None:
                notes.append({"coin": coin, "raison": "CROSS_VENUE_MORE_DATA"})   # edge signalé, carnet hedge absent
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
            book = books_par_coin.get(c["coin"])
            mid = prix_par_coin.get(c["coin"])
            if not book or not book.get("bids") or not book.get("asks") or not isinstance(mid, (int, float)):
                fills.append({"cle": c["cle"], "execute": False, "raison": "MORE_DATA"})
                continue
            rk = filtrer_risque(cand, notional_max=self.notional_max, coin=c["coin"], now_ms=ts_ms,
                                drawdown_gate=self.drawdown_gate, verrou=self.verrou,
                                equity=self.executeur.ledger.equity_usdc)
            if not rk.get("autorise"):
                fills.append({"cle": c["cle"], "execute": False, "raison": rk.get("raison")})
                continue
            res = self.executeur.executer(cand, book=book, mid=mid, ts_ms=ts_ms)
            fills.append({"cle": c["cle"], "execute": res.get("execute"), "action": res.get("action"),
                          "raison": res.get("raison"), "fill_price": res.get("fill_price"),
                          "filled_notional": res.get("filled_notional")})
        cross_venue = [self._executer_cross_venue(job, ts_ms=ts_ms) for job in jobs_cv]
        # ts_ms absent/non numérique (ex. log sans timestamp) → tick non causal : événements déjà rejetés à
        # l'admission, on NE marque PAS (fail-closed, jamais de mark_to_market fabriqué à un temps inventé).
        if isinstance(ts_ms, (int, float)) and not isinstance(ts_ms, bool):
            self.executeur.marquer(marks or {k: v for k, v in prix_par_coin.items()
                                             if isinstance(v, (int, float))}, ts_ms=ts_ms)
        tick = {"ts_ms": ts_ms, "rejets": rejets, "notes": notes,
                "self_trade": nr["self_trade"]["self_trade"], "n_candidats": len(nr["candidats"]),
                "fills": fills, "cross_venue": cross_venue, "pnl": self.executeur.pnl()}
        self.trace.append(tick)
        return tick

    def traiter_replay(self, flux: list[dict[str, Any]], *, leader_equity_par_vault: dict[str, Any],
                       routes_par_cle: dict[str, list] | None = None) -> dict[str, Any]:
        """Groupe un flux plat d'événements par ts_ms (ordre stable) et traite chaque tick. `flux` provient TOUJOURS
        du feed_adapter en amont (mêmes événements pour tous les points d'entrée)."""
        groupes: "OrderedDict[Any, list]" = OrderedDict()
        for ev in flux:
            groupes.setdefault(ev.get("ts_ms"), []).append(ev)
        for _, evs in groupes.items():
            self.traiter_tick(evs, leader_equity_par_vault=leader_equity_par_vault,
                              routes_par_cle=routes_par_cle)
        return self.resume()

    def resume(self) -> dict[str, Any]:
        n_fills = sum(1 for t in self.trace for f in t["fills"] if f.get("execute"))
        n_cv = sum(1 for t in self.trace for cv in t.get("cross_venue", []) if cv.get("execute"))
        return {"pnl": self.executeur.pnl(), "ticks": len(self.trace), "fills_executes": n_fills,
                "cross_venue_executes": n_cv, "snapshot": self.executeur.ledger.snapshot()}


__all__ = ["MegaCablage"]
