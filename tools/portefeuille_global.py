"""PORTEFEUILLE GLOBAL VIVANT ET PERSISTANT DU RUN (Flo 26/07, AF-P3). UN seul objet pour tout le run :
capital/cash/marge uniques, positions PERSISTANTES, OPEN/ADD/REDUCE/CLOSE/FLIP, expositions simultanées,
concurrence RÉELLE entre candidats (refus si capital insuffisant), checkpoint + REPRISE des positions après
crash, valorisation live, equity curve chronologique, drawdown réel. La réconciliation compare INDÉPENDAMMENT
le ledger reconstruit au snapshot courant (`coherent` calculé, JAMAIS codé True). 0 ordre réel, paper-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

COUTS = ("fees_bps", "spread_bps", "slippage_bps", "impact_bps", "funding_bps", "latency_bps")


def _cost_usd(notional: float, couts: dict | None) -> float:
    if not couts:
        return 0.0
    return abs(notional) * sum(float(couts.get(k) or 0.0) for k in COUTS) / 1e4


class PortefeuilleGlobal:
    """État sur disque : state.json (snapshot) + ledger.jsonl (append-only). Reprenable après crash."""

    def __init__(self, dossier: Path, *, capital_initial: float = 1000.0, levier: float = 3.0,
                 max_expo_coin_frac: float = 0.5):
        self.dir = Path(dossier)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.ledger_path = self.dir / "ledger.jsonl"
        self.max_expo_coin_frac = float(max_expo_coin_frac)
        st = self._charger()
        self.capital_initial = st.get("capital_initial", float(capital_initial))
        self.levier = st.get("levier", float(levier))
        self.cash = st.get("cash", self.capital_initial)
        self.realized = st.get("realized", 0.0)
        self.frais_cumules = st.get("frais_cumules", 0.0)
        self.pic_equity = st.get("pic_equity", self.capital_initial)
        self.max_drawdown = st.get("max_drawdown", 0.0)
        self.positions = st.get("positions", {})             # PERSISTANTES : reprises telles quelles après crash
        self._marks = st.get("marks", {})
        self.turnover = st.get("turnover", 0.0)

    # ── persistance ──
    def _charger(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _sauver(self):
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "capital_initial": self.capital_initial, "levier": self.levier, "cash": self.cash,
            "realized": self.realized, "frais_cumules": self.frais_cumules, "pic_equity": self.pic_equity,
            "max_drawdown": self.max_drawdown, "positions": self.positions, "marks": self._marks,
            "turnover": self.turnover}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _append(self, evt: dict):
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")

    # ── marge / expositions ──
    def _marge(self, notional: float) -> float:
        return abs(notional) / self.levier

    def marge_engagee(self) -> float:
        return sum(self._marge(p["notional"]) for p in self.positions.values())

    def exposition_coin(self, coin: str) -> float:
        return sum(abs(p["notional"]) for p in self.positions.values() if p["coin"] == coin)

    # ── cycle de vie ──
    def ouvrir(self, position_id: str, *, coin: str, sens: int, notional: float, prix: float,
               ts_ms: float = 0.0, couts: dict | None = None) -> dict:
        if position_id in self.positions:
            return {"refus": "POSITION_EXISTE"}
        marge = self._marge(notional); cout = _cost_usd(notional, couts)
        if marge + cout > self.cash + 1e-9:                  # capital PARTAGÉ : concurrence réelle
            return {"refus": "CAPITAL_INSUFFISANT", "cash": round(self.cash, 4)}
        if (self.exposition_coin(coin) + abs(notional)) > self.capital_initial * self.max_expo_coin_frac:
            return {"refus": "LIMITE_CONCENTRATION_COIN", "coin": coin}
        self.cash -= (marge + cout); self.realized -= cout; self.frais_cumules += cout; self.turnover += abs(notional)
        self.positions[position_id] = {"position_id": position_id, "coin": coin, "sens": int(sens),
                                       "notional": float(notional), "entry_px": float(prix)}
        self._marks[coin] = float(prix)
        return self._evt("OPEN", position_id, coin=coin, sens=sens, notional=notional, prix=prix, cout_usd=cout, ts_ms=ts_ms)

    def ajouter(self, position_id: str, *, notional: float, prix: float, ts_ms: float = 0.0, couts: dict | None = None) -> dict:
        p = self.positions.get(position_id)
        if not p:
            return {"refus": "POSITION_ABSENTE"}
        marge = self._marge(notional); cout = _cost_usd(notional, couts)
        if marge + cout > self.cash + 1e-9:
            return {"refus": "CAPITAL_INSUFFISANT"}
        tot = p["notional"] + notional
        p["entry_px"] = (p["entry_px"] * p["notional"] + prix * notional) / tot if tot else prix
        p["notional"] = tot
        self.cash -= (marge + cout); self.realized -= cout; self.frais_cumules += cout; self.turnover += abs(notional)
        self._marks[p["coin"]] = float(prix)
        return self._evt("ADD", position_id, coin=p["coin"], sens=p["sens"], notional=notional, prix=prix, cout_usd=cout, ts_ms=ts_ms)

    def _pnl(self, p, prix, notional):
        return 0.0 if p["entry_px"] <= 0 else p["sens"] * (prix - p["entry_px"]) / p["entry_px"] * notional

    def reduire(self, position_id: str, *, fraction: float, prix: float, ts_ms: float = 0.0, couts: dict | None = None) -> dict:
        p = self.positions.get(position_id)
        if not p:
            return {"refus": "POSITION_ABSENTE"}
        fraction = max(0.0, min(1.0, float(fraction)))
        nr = p["notional"] * fraction
        pnl = self._pnl(p, prix, nr); cout = _cost_usd(nr, couts); ml = self._marge(nr)
        self.cash += ml + pnl - cout; self.realized += pnl - cout; self.frais_cumules += cout; self.turnover += abs(nr)
        p["notional"] -= nr; self._marks[p["coin"]] = float(prix)
        t = "CLOSE" if p["notional"] <= 1e-9 else "REDUCE"
        evt = self._evt(t, position_id, coin=p["coin"], sens=p["sens"], notional=nr, prix=prix, cout_usd=cout, pnl_usd=pnl, ts_ms=ts_ms)
        if p["notional"] <= 1e-9:
            self.positions.pop(position_id, None)
        return evt

    def fermer(self, position_id: str, *, prix: float, ts_ms: float = 0.0, couts: dict | None = None) -> dict:
        return self.reduire(position_id, fraction=1.0, prix=prix, ts_ms=ts_ms, couts=couts)

    def flip(self, position_id: str, *, prix: float, ts_ms: float = 0.0, couts: dict | None = None) -> dict:
        """FLIP : ferme la position et en rouvre une de sens OPPOSÉ, même notionnel (si le capital suit)."""
        p = self.positions.get(position_id)
        if not p:
            return {"refus": "POSITION_ABSENTE"}
        coin, sens, notional = p["coin"], p["sens"], p["notional"]
        self.fermer(position_id, prix=prix, ts_ms=ts_ms, couts=couts)
        return self.ouvrir(position_id + ":flip", coin=coin, sens=-sens, notional=notional, prix=prix, ts_ms=ts_ms, couts=couts)

    # ── valorisation ──
    def marquer(self, prix_par_coin: dict):
        for c, px in (prix_par_coin or {}).items():
            self._marks[c] = float(px)
        self._sauver()

    def pnl_latent(self) -> float:
        return sum(self._pnl(p, self._marks.get(p["coin"], p["entry_px"]), p["notional"]) for p in self.positions.values())

    def equity(self) -> float:
        return self.cash + self.marge_engagee() + self.pnl_latent()

    def _evt(self, type_, position_id, **kw) -> dict:
        evt = {"type": type_, "position_id": position_id, **kw,
               "cash_apres": round(self.cash, 6), "realized_apres": round(self.realized, 6)}
        self._append(evt)
        eq = self.equity(); self.pic_equity = max(self.pic_equity, eq); self.max_drawdown = max(self.max_drawdown, self.pic_equity - eq)
        self._sauver()                                        # CHECKPOINT à chaque événement (reprise après crash)
        return evt

    # ── réconciliation indépendante ──
    def reconcilier(self) -> dict:
        """Reconstruit realized + cash depuis le LEDGER (streaming) et compare au snapshot courant. `coherent`
        est CALCULÉ (jamais codé True)."""
        cash = self.capital_initial; realized = 0.0; marge = 0.0
        n = {"OPEN": 0, "ADD": 0, "REDUCE": 0, "CLOSE": 0}
        if self.ledger_path.exists():
            for l in self.ledger_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    e = json.loads(l)
                except ValueError:
                    continue
                t = e.get("type"); cout = float(e.get("cout_usd") or 0.0); pnl = float(e.get("pnl_usd") or 0.0)
                m = abs(float(e.get("notional") or 0.0)) / self.levier
                if t in ("OPEN", "ADD"):
                    cash -= (m + cout); realized -= cout; marge += m; n[t] += 1
                elif t in ("REDUCE", "CLOSE"):
                    cash += (m + pnl - cout); realized += pnl - cout; marge = max(0.0, marge - m); n[t] += 1
        coherent = abs(cash - self.cash) < 1e-4 and abs(realized - self.realized) < 1e-4
        roi_total = (self.equity() - self.capital_initial) / self.capital_initial * 100.0 if self.capital_initial else None
        deploye = max(self.capital_initial - self.cash, 1e-9)
        return {"capital_initial": round(self.capital_initial, 4), "cash_snapshot": round(self.cash, 4),
                "cash_ledger": round(cash, 4), "realized_snapshot": round(self.realized, 4),
                "realized_ledger": round(realized, 4), "equity": round(self.equity(), 4),
                "drawdown_usd": round(self.max_drawdown, 4), "positions_ouvertes": len(self.positions),
                "roi_total_pct": (round(roi_total, 4) if roi_total is not None else None),
                "roi_deploye_pct": round(self.realized / deploye * 100.0, 4), "turnover": round(self.turnover, 4),
                "evenements": n, "coherent": bool(coherent)}


__all__ = ["PortefeuilleGlobal", "COUTS"]
