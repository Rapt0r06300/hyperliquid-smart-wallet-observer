"""CANONICAL EVENT STORE + MATURATION LIVE PAR HORIZON (Flo 26/07, AF-P1 + FX-8).

Stockage canonique persistant au niveau du run : runtime/research_lab/continuous/<run_id>/canonical/. Chaque
événement de marché (BBO/L2/trade) est normalisé, dédupliqué, et chaque HORIZON mûrit SÉPARÉMENT :

  PENDING  : horizon reçu, en attente de son futur ;
  READY    : le vrai bid/ask (et L2) FUTUR à ts+horizon a été joint -> fwd_bid/fwd_ask ; exécutable ;
  CONSUMED : cet horizon a été consommé une seule fois par le forward/replay ;
  EXPIRED  : horizon dépassé sans futur suffisant (raison).

FX-8 : (1) l'horodatage privilégie exchange_ts (horloge locale seulement en secours), (2) READY_250MS peut être
consommé SANS attendre READY_30000MS, (3) le vrai L2 futur est joint s'il est présent, (4) l'état n'est plus un
`state.json` géant réécrit à chaque fois : c'est un JOURNAL append-only + des SNAPSHOTS bornés (rotation +
compaction, jamais de perte), avec reprise après crash par rejeu du journal. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

HORIZONS_DEFAUT = (250, 1000, 5000, 30000)
SNAPSHOT_EVERY_DEFAUT = 500          # au-delà de N enregistrements de journal -> compaction (snapshot + rotation)


def _sha(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


class CanonicalStore:
    """Journal append-only (journal.jsonl) + snapshot borné (snapshot.json) : idempotent, reprenable, compacté.
    L'état courant d'un événement = le dernier enregistrement le concernant. Maturation PAR HORIZON."""

    def __init__(self, rundir: Path, *, horizons=HORIZONS_DEFAUT, grace_ms: float = 0.0,
                 snapshot_every: int = SNAPSHOT_EVERY_DEFAUT):
        self.dir = Path(rundir) / "canonical"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.horizons = tuple(int(h) for h in horizons)
        self.grace_ms = float(grace_ms)
        self.snapshot_every = int(snapshot_every)
        self.snapshot_path = self.dir / "snapshot.json"
        self.journal_path = self.dir / "journal.jsonl"
        self.ready_path = self.dir / "ready.jsonl"           # audit : un épisode par horizon devenu READY
        self.archive_dir = self.dir / "journal_archive"
        self.seq = 0
        self._ops_depuis_snapshot = 0
        self.etat = self._charger()                          # {event_id: {coin, ts_ms, ts_source, bid, ask, h:{...}}}

    # ── persistance : snapshot borné + journal append-only + reprise ──
    def _charger(self) -> dict:
        etat, seq = {}, 0
        try:
            snap = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            etat = snap.get("etat", {}) or {}
            seq = int(snap.get("seq", 0))
        except (OSError, ValueError):
            etat, seq = {}, 0
        n_journal = 0
        if self.journal_path.exists():                       # REPRISE CRASH : rejeu du journal post-snapshot
            with self.journal_path.open("r", encoding="utf-8", errors="ignore") as f:
                for l in f:
                    l = l.strip()
                    if not l:
                        continue
                    try:
                        rec = json.loads(l)
                    except ValueError:
                        continue
                    eid = rec.get("event_id")
                    if eid is not None:
                        etat[eid] = rec.get("etat", rec)     # last-write-wins par event_id
                        seq = max(seq, int(rec.get("seq", seq)))
                        n_journal += 1
        self.seq = seq
        self._ops_depuis_snapshot = n_journal
        return etat

    def _journaliser(self, eids):
        """Append-only : écrit l'état COURANT des events modifiés. Compacte si le journal dépasse le seuil."""
        if not eids:
            return
        with self.journal_path.open("a", encoding="utf-8") as f:
            for eid in eids:
                self.seq += 1
                f.write(json.dumps({"seq": self.seq, "event_id": eid, "etat": self.etat[eid]}, ensure_ascii=False) + "\n")
                self._ops_depuis_snapshot += 1
        if self._ops_depuis_snapshot >= self.snapshot_every:
            self._compacter()

    def _compacter(self):
        """Écrit un snapshot borné (état courant complet) et ARCHIVE le journal (jamais supprimé), puis le vide."""
        tmp = self.snapshot_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"seq": self.seq, "etat": self.etat}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.snapshot_path)
        if self.journal_path.exists() and self.journal_path.stat().st_size > 0:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            os.replace(self.journal_path, self.archive_dir / ("journal_%d.jsonl" % self.seq))  # PRÉSERVÉ
        self.journal_path.write_text("", encoding="utf-8")
        self._ops_depuis_snapshot = 0

    def compacter(self) -> dict:
        """Compaction explicite (utilisable par un test ou une maintenance). Rend l'état après compaction."""
        self._compacter()
        return {"seq": self.seq, "snapshot": str(self.snapshot_path), "n_events": len(self.etat)}

    # ── ingestion (dédup, exchange_ts prioritaire) ──
    def ingerer(self, events) -> dict:
        n_new = n_dup = 0
        changed = []
        for e in events:
            coin = str(e.get("coin") or e.get("symbol") or "").upper()
            # FX-8 : exchange_ts PRIORITAIRE ; l'horloge locale (ts_wall_ms) seulement en dernier secours.
            ts, ts_source = None, None
            for cle in ("exchange_ts", "ts_ms", "ts_wall_ms"):
                if e.get(cle) is not None:
                    ts, ts_source = e.get(cle), cle
                    break
            bid, ask = e.get("bid"), e.get("ask")
            if not coin or ts is None or bid is None or ask is None:
                continue
            eid = _sha(coin, ts, e.get("_source", ""))
            if eid in self.etat:
                n_dup += 1
                continue
            self.etat[eid] = {"event_id": eid, "coin": coin, "ts_ms": float(ts), "ts_source": ts_source,
                              "bid": float(bid), "ask": float(ask),
                              "h": {str(h): {"st": "PENDING", "fb": None, "fa": None, "fbids": None,
                                             "fasks": None, "raison": None} for h in self.horizons}}
            changed.append(eid)
            n_new += 1
        self._journaliser(changed)
        return {"n_pending_ajoutes": n_new, "n_dupliques": n_dup, "backlog": self.backlog()}

    # ── maturation PAR HORIZON ──
    def maturer(self, marche_par_coin: dict, *, maintenant_ms: float) -> dict:
        """Pour chaque HORIZON encore PENDING d'un événement, joint le vrai bid/ask (et L2 si présent) FUTUR au
        tick à ts+horizon. READY_250MS devient exécutable SANS attendre READY_30000MS. EXPIRED si l'échéance de
        CET horizon est dépassée sans futur suffisant. Chaque horizon READY est écrit une fois dans ready.jsonl."""
        maries = expires = 0
        changed = []
        futurs = {c: sorted(v, key=lambda t: t["ts_ms"]) for c, v in (marche_par_coin or {}).items()}
        fout = self.ready_path.open("a", encoding="utf-8")
        try:
            for eid, ev in self.etat.items():
                ticks = futurs.get(ev["coin"], [])
                touche = False
                for h in self.horizons:
                    hs = ev["h"][str(h)]
                    if hs["st"] != "PENDING":
                        continue
                    cible = ev["ts_ms"] + h
                    t = next((x for x in ticks if x["ts_ms"] >= cible), None)
                    if t is not None:
                        hs["st"] = "READY"; hs["fb"] = float(t["bid"]); hs["fa"] = float(t["ask"])
                        hs["fbids"] = t.get("bids"); hs["fasks"] = t.get("asks")   # vrai L2 futur si présent
                        maries += 1; touche = True
                        fout.write(json.dumps(self.episode_horizon(ev, h), ensure_ascii=False) + "\n")
                    elif maintenant_ms - ev["ts_ms"] > h + self.grace_ms:          # échéance de CET horizon dépassée
                        hs["st"] = "EXPIRED"; hs["raison"] = "FUTUR_INSUFFISANT_horizon_%d" % h
                        expires += 1; touche = True
                if touche:
                    changed.append(eid)
        finally:
            fout.close()
        self._journaliser(changed)
        return {"maries": maries, "expires": expires, "backlog": self.backlog(), "compte": self.compte()}

    def episode_horizon(self, ev: dict, h: int) -> dict:
        """Épisode canonique exécutable pour UN horizon (FWD_BOOK). Porte le vrai carnet futur si joint."""
        hs = ev["h"][str(h)]
        ep = {"episode_id": "%s:%d" % (ev["event_id"], h), "event_id": ev["event_id"], "coin": ev["coin"],
              "regime": "live", "ts_ms": ev["ts_ms"], "horizon_ms": int(h), "bid": ev["bid"], "ask": ev["ask"],
              "fwd_bid": {int(h): hs["fb"]}, "fwd_ask": {int(h): hs["fa"]}}
        if hs.get("fbids") is not None and hs.get("fasks") is not None:
            ep["fwd_bids"], ep["fwd_asks"] = hs["fbids"], hs["fasks"]
        return ep

    def episode(self, ev: dict) -> dict:
        """Épisode multi-horizons (agrège tous les horizons READY/CONSUMED d'un événement) — pour compat/audit."""
        fb = {int(k): v["fb"] for k, v in ev["h"].items() if v["fb"] is not None}
        fa = {int(k): v["fa"] for k, v in ev["h"].items() if v["fa"] is not None}
        return {"episode_id": ev["event_id"], "coin": ev["coin"], "regime": "live", "ts_ms": ev["ts_ms"],
                "bid": ev["bid"], "ask": ev["ask"], "fwd_bid": fb, "fwd_ask": fa}

    # ── consommation (par horizon, une seule fois) ──
    def consommer(self) -> list:
        """Rend un épisode par événement AYANT au moins un horizon READY non consommé, restreint à CES horizons,
        et marque ces horizons CONSUMED (jamais deux fois). Un horizon 250 peut donc être consommé avant que 30000
        ne soit mûr ; au passage suivant, seul l'horizon nouvellement mûri est rendu."""
        out = []
        changed = []
        for eid, ev in self.etat.items():
            prets = [int(k) for k, v in ev["h"].items() if v["st"] == "READY"]
            if not prets:
                continue
            fb = {h: ev["h"][str(h)]["fb"] for h in prets}
            fa = {h: ev["h"][str(h)]["fa"] for h in prets}
            episode = {"episode_id": ev["event_id"], "event_id": ev["event_id"], "coin": ev["coin"],
                       "regime": "live", "ts_ms": ev["ts_ms"], "bid": ev["bid"], "ask": ev["ask"],
                       "horizons": sorted(prets), "fwd_bid": fb, "fwd_ask": fa}
            out.append(episode)
            for h in prets:
                ev["h"][str(h)]["st"] = "CONSUMED"
            changed.append(eid)
        self._journaliser(changed)
        return out

    # ── diagnostics ──
    def backlog(self) -> int:
        """Nombre d'ÉVÉNEMENTS ayant au moins un horizon PENDING (la granularité horizon est dans compte())."""
        return sum(1 for ev in self.etat.values() if any(v["st"] == "PENDING" for v in ev["h"].values()))

    def backlog_horizons(self) -> int:
        """Nombre d'HORIZONS encore PENDING (granularité fine)."""
        return sum(1 for ev in self.etat.values() for v in ev["h"].values() if v["st"] == "PENDING")

    def compte(self) -> dict:
        """Compte au niveau ÉVÉNEMENT (statut agrégé) ET au niveau HORIZON (détail par état)."""
        evx = {"PENDING": 0, "READY": 0, "CONSUMED": 0, "EXPIRED": 0}
        horx = {"PENDING": 0, "READY": 0, "CONSUMED": 0, "EXPIRED": 0}
        for ev in self.etat.values():
            sts = [v["st"] for v in ev["h"].values()]
            for s in sts:
                horx[s] = horx.get(s, 0) + 1
            if any(s == "PENDING" for s in sts):
                evx["PENDING"] += 1
            elif any(s == "READY" for s in sts):
                evx["READY"] += 1
            elif all(s == "CONSUMED" for s in sts):
                evx["CONSUMED"] += 1
            else:
                evx["EXPIRED"] += 1
        return {**evx, "par_horizon": horx, "n_events": len(self.etat)}


__all__ = ["CanonicalStore", "HORIZONS_DEFAUT", "SNAPSHOT_EVERY_DEFAUT"]
