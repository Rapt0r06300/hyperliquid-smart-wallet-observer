"""REGISTRE RUN-LEVEL DES CANDIDATS FIGÉS + SUIVI LIVE (Flo 26/07, FX-5).

Le forward historique (sur archive, après le gel) est un PRÉ-FORWARD : il teste un candidat avant le vrai suivi
live, mais ce N'EST PAS le « forward live ». Le forward LIVE réel = ce registre : chaque candidat figé est
suivi cycle après cycle sur les épisodes qui arrivent dans le CanonicalStore APRÈS son freeze_exchange_ts.

Chaque entrée porte : candidate_id, freeze_exchange_ts, last_forward_event_id, durée live, PnL/ROI/DD live,
n_episodes_live. GARANTIE DURE : une pépite « positive en live » ne peut utiliser QUE des épisodes dont
l'exchange_ts est STRICTEMENT supérieur à son freeze_exchange_ts (jamais de réutilisation d'avant-gel). Les
candidats des cycles précédents CONTINUENT d'être suivis à chaque nouveau cycle. Persistant, reprenable.
0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _ts_episode(e: dict):
    """Horloge d'un épisode : exchange_ts prioritaire, puis ts_ms (cohérent avec le CanonicalStore, FX-8)."""
    for cle in ("exchange_ts", "ts_ms", "ts_wall_ms"):
        if e.get(cle) is not None:
            try:
                return float(e[cle])
            except (TypeError, ValueError):
                continue
    return None


def filtrer_apres_freeze(episodes, freeze_exchange_ts: float) -> list:
    """Ne garde QUE les épisodes STRICTEMENT postérieurs au gel (exchange_ts > freeze_exchange_ts). Garde-fou
    dur contre l'utilisation d'un épisode d'avant-gel pour prétendre à un edge live."""
    fz = float(freeze_exchange_ts)
    out = []
    for e in episodes or []:
        ts = _ts_episode(e)
        if ts is not None and ts > fz:
            out.append(e)
    return out


class RegistreCandidatsLive:
    """État persistant au niveau du run (registre_candidats_live.json). Idempotent : un candidat n'est jamais
    re-figé (son freeze_exchange_ts est immuable une fois posé)."""

    def __init__(self, rundir: Path):
        self.path = Path(rundir) / "registre_candidats_live.json"
        self.etat = self._charger()                          # {candidate_id: {...}}

    def _charger(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _sauver(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.etat, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def figer(self, candidate_id: str, *, freeze_exchange_ts: float, meta: dict | None = None) -> dict:
        """Fige un candidat (immuable). Si déjà figé, renvoie l'entrée existante SANS changer son freeze."""
        if candidate_id in self.etat:
            return self.etat[candidate_id]
        self.etat[candidate_id] = {
            "candidate_id": candidate_id, "freeze_exchange_ts": float(freeze_exchange_ts),
            "last_forward_event_id": None, "n_episodes_live": 0, "duree_live_ms": 0.0,
            "pnl_live_bps": 0.0, "roi_live_pct": 0.0, "dd_live_bps": 0.0,
            "positif_live": False, "meta": meta or {}, "fige_ms": int(time.time() * 1000)}
        self._sauver()
        return self.etat[candidate_id]

    def episodes_admissibles(self, candidate_id: str, episodes) -> list:
        """Épisodes utilisables pour CE candidat = STRICTEMENT après SON freeze_exchange_ts (garantie dure)."""
        c = self.etat.get(candidate_id)
        if not c:
            return []
        return filtrer_apres_freeze(episodes, c["freeze_exchange_ts"])

    def suivre(self, candidate_id: str, *, nets_live, last_event_id=None, maintenant_ms=None) -> dict | None:
        """Met à jour le suivi live d'un candidat à partir des nets (bps) de SES épisodes admissibles. PnL/ROI/DD
        cumulés sur le live UNIQUEMENT. `positif_live` n'est vrai que s'il y a de la donnée live ET un cumul > 0."""
        c = self.etat.get(candidate_id)
        if not c:
            return None
        nets = [float(x) for x in (nets_live or []) if isinstance(x, (int, float))]
        cum = 0.0; pic = 0.0; dd = 0.0
        for x in nets:
            cum += x
            pic = max(pic, cum)
            dd = max(dd, pic - cum)
        c["n_episodes_live"] = len(nets)
        c["pnl_live_bps"] = round(cum, 4)
        c["roi_live_pct"] = round(cum / 100.0, 4)            # bps -> % (1 bps = 0.01 %)
        c["dd_live_bps"] = round(dd, 4)
        c["positif_live"] = bool(nets and cum > 0)
        if last_event_id is not None:
            c["last_forward_event_id"] = last_event_id
        if maintenant_ms is not None:
            c["duree_live_ms"] = round(float(maintenant_ms) - c["freeze_exchange_ts"], 2)
        self._sauver()
        return c

    def candidats(self) -> list:
        return list(self.etat.values())

    def resume(self) -> dict:
        cs = self.candidats()
        return {"n_candidats": len(cs), "n_positifs_live": sum(1 for c in cs if c.get("positif_live")),
                "n_avec_donnee_live": sum(1 for c in cs if (c.get("n_episodes_live") or 0) > 0)}


__all__ = ["RegistreCandidatsLive", "filtrer_apres_freeze"]
