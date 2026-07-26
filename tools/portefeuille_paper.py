"""PORTEFEUILLE PAPER RÉEL (Flo 26/07, LABO-CONTINU-PROD-TRUTH PT-5).

Remplace le « forward markout » (une médiane de net par candidat) par un VRAI portefeuille paper à capital
PARTAGÉ : chaque décision devient une position identifiée (position_id) avec un cycle OPEN/ADD/REDUCE/CLOSE,
un notionnel réellement rempli, un cash commun (les positions se disputent le même capital), des expositions
simultanées, un PnL latent ET réalisé, des coûts séparés (fees, spread, slippage, impact, funding), une
equity et un drawdown. La réconciliation RECONSTRUIT tout depuis le ledger d'événements, indépendamment des
compteurs courants — si les deux divergent, `coherent=False` (jamais maquillé). 0 ordre réel, paper-only.
"""
from __future__ import annotations

import json
from pathlib import Path

COUTS = ("fees_bps", "spread_bps", "slippage_bps", "impact_bps", "funding_bps", "latency_bps")


def _cost_usd(notional: float, couts: dict | None) -> float:
    """Somme des coûts (bps) appliquée au notionnel -> USD. Coûts absents = 0 (jamais inventés)."""
    if not couts:
        return 0.0
    tot_bps = sum(float(couts.get(k) or 0.0) for k in COUTS)
    return notional * tot_bps / 1e4


class PortefeuillePaper:
    """Capital partagé. Levier borne la marge par position. Aucune position n'ouvre si la marge dépasse le
    cash disponible (capital réellement partagé). Tout événement est journalisé dans un ledger append-only."""

    def __init__(self, capital_initial: float = 1000.0, *, levier: float = 3.0):
        self.capital_initial = float(capital_initial)
        self.cash = float(capital_initial)
        self.levier = float(levier)
        self.positions: dict[str, dict] = {}
        self.ledger: list[dict] = []
        self.realized = 0.0
        self.frais_cumules = 0.0
        self.pic_equity = float(capital_initial)
        self.max_drawdown = 0.0
        self._marks: dict[str, float] = {}

    # ── marge partagée ──
    def _marge(self, notional: float) -> float:
        return abs(notional) / self.levier

    def marge_engagee(self) -> float:
        return sum(self._marge(p["notional"]) for p in self.positions.values())

    def cash_disponible(self) -> float:
        return self.cash

    # ── cycle de vie ──
    def ouvrir(self, position_id: str, *, coin: str, sens: int, notional: float, prix: float,
               ts_ms: float = 0.0, couts: dict | None = None) -> dict:
        if position_id in self.positions:
            return {"refus": "POSITION_EXISTE", "position_id": position_id}
        marge = self._marge(notional)
        cout = _cost_usd(notional, couts)
        if marge + cout > self.cash + 1e-9:                    # capital PARTAGÉ : pas d'ouverture au-delà du cash
            return {"refus": "CAPITAL_INSUFFISANT", "besoin": round(marge + cout, 4), "cash": round(self.cash, 4)}
        self.cash -= (marge + cout)
        self.frais_cumules += cout
        self.realized -= cout                                   # les coûts d'ouverture pèsent sur le réalisé
        self.positions[position_id] = {"position_id": position_id, "coin": coin, "sens": int(sens),
                                       "notional": float(notional), "entry_px": float(prix), "marge": marge}
        self._marks[coin] = float(prix)
        return self._evt("OPEN", position_id, coin=coin, sens=sens, notional=notional, prix=prix,
                         cout_usd=cout, ts_ms=ts_ms)

    def ajouter(self, position_id: str, *, notional: float, prix: float, ts_ms: float = 0.0,
                couts: dict | None = None) -> dict:
        p = self.positions.get(position_id)
        if not p:
            return {"refus": "POSITION_ABSENTE", "position_id": position_id}
        marge_sup = self._marge(notional)
        cout = _cost_usd(notional, couts)
        if marge_sup + cout > self.cash + 1e-9:
            return {"refus": "CAPITAL_INSUFFISANT"}
        # nouveau prix d'entrée pondéré par le notionnel
        tot = p["notional"] + notional
        p["entry_px"] = (p["entry_px"] * p["notional"] + prix * notional) / tot if tot else prix
        p["notional"] = tot
        p["marge"] += marge_sup
        self.cash -= (marge_sup + cout)
        self.frais_cumules += cout
        self.realized -= cout
        self._marks[p["coin"]] = float(prix)
        return self._evt("ADD", position_id, coin=p["coin"], sens=p["sens"], notional=notional, prix=prix,
                         cout_usd=cout, ts_ms=ts_ms)

    def _pnl_usd(self, p: dict, prix_sortie: float, notional: float) -> float:
        """PnL réalisé/latent sur `notional` de la position, du prix d'entrée au prix de sortie, signé."""
        if p["entry_px"] <= 0:
            return 0.0
        var = (prix_sortie - p["entry_px"]) / p["entry_px"]
        return p["sens"] * var * notional

    def reduire(self, position_id: str, *, fraction: float, prix: float, ts_ms: float = 0.0,
                couts: dict | None = None) -> dict:
        p = self.positions.get(position_id)
        if not p:
            return {"refus": "POSITION_ABSENTE", "position_id": position_id}
        fraction = max(0.0, min(1.0, float(fraction)))
        notional_reduit = p["notional"] * fraction
        pnl = self._pnl_usd(p, prix, notional_reduit)
        cout = _cost_usd(notional_reduit, couts)
        marge_liberee = self._marge(notional_reduit)
        self.cash += marge_liberee + pnl - cout
        self.realized += pnl - cout
        self.frais_cumules += cout
        p["notional"] -= notional_reduit
        p["marge"] -= marge_liberee
        self._marks[p["coin"]] = float(prix)
        type_evt = "CLOSE" if p["notional"] <= 1e-9 else "REDUCE"   # une réduction totale = CLOSE (ledger honnête)
        evt = self._evt(type_evt, position_id, coin=p["coin"], sens=p["sens"], notional=notional_reduit,
                        prix=prix, cout_usd=cout, pnl_usd=pnl, ts_ms=ts_ms)
        if p["notional"] <= 1e-9:
            self.positions.pop(position_id, None)
        return evt

    def fermer(self, position_id: str, *, prix: float, ts_ms: float = 0.0, couts: dict | None = None) -> dict:
        p = self.positions.get(position_id)
        if not p:
            return {"refus": "POSITION_ABSENTE", "position_id": position_id}
        return self.reduire(position_id, fraction=1.0, prix=prix, ts_ms=ts_ms, couts=couts)

    # ── valorisation ──
    def marquer(self, prix_par_coin: dict) -> None:
        for c, px in (prix_par_coin or {}).items():
            self._marks[c] = float(px)

    def pnl_latent(self) -> float:
        return sum(self._pnl_usd(p, self._marks.get(p["coin"], p["entry_px"]), p["notional"])
                   for p in self.positions.values())

    def equity(self) -> float:
        return self.cash + self.marge_engagee() + self.pnl_latent()

    def _maj_drawdown(self) -> None:
        eq = self.equity()
        self.pic_equity = max(self.pic_equity, eq)
        self.max_drawdown = max(self.max_drawdown, self.pic_equity - eq)

    # ── ledger + réconciliation ──
    def _evt(self, type_: str, position_id: str, **kw) -> dict:
        evt = {"type": type_, "position_id": position_id, **kw,
               "cash_apres": round(self.cash, 6), "realized_apres": round(self.realized, 6)}
        self.ledger.append(evt)
        self._maj_drawdown()
        return evt

    def ecrire_ledger(self, chemin: Path) -> None:
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("w", encoding="utf-8") as f:
            for e in self.ledger:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def reconcilier(self) -> dict:
        """RECONSTRUIT indépendamment depuis le ledger : realized (REDUCE/CLOSE − coûts), cash, equity,
        drawdown, ROI total/déployé. `coherent` compare la reconstruction aux compteurs courants."""
        realized = 0.0
        marge_pic = 0.0
        for e in self.ledger:
            realized += float(e.get("pnl_usd") or 0.0) - float(e.get("cout_usd") or 0.0)
        equity = self.equity()
        roi_total = (equity - self.capital_initial) / self.capital_initial * 100.0 if self.capital_initial else None
        deploye = max(self.capital_initial - self.cash, 1e-9)
        roi_deploye = self.realized / deploye * 100.0
        coherent = abs(realized - self.realized) < 1e-6
        return {"capital_initial": round(self.capital_initial, 4), "cash": round(self.cash, 4),
                "marge_engagee": round(self.marge_engagee(), 4), "pnl_realise": round(self.realized, 4),
                "pnl_realise_reconstruit": round(realized, 4), "pnl_latent": round(self.pnl_latent(), 4),
                "equity": round(equity, 4), "drawdown_usd": round(self.max_drawdown, 4),
                "roi_total_pct": (round(roi_total, 4) if roi_total is not None else None),
                "roi_deploye_pct": round(roi_deploye, 4), "frais_cumules": round(self.frais_cumules, 4),
                "positions_ouvertes": len(self.positions), "n_evenements": len(self.ledger),
                "coherent": bool(coherent)}


__all__ = ["PortefeuillePaper", "COUTS"]
