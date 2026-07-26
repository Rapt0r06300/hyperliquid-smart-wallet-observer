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
        self.attente_path = Path(rundir) / "registre_candidats_live_attente.json"
        self.etat = self._charger(self.path)                 # {candidate_id: {...}} (candidats GELÉS)
        self.attente = self._charger(self.attente_path)      # {candidate_id: {...}} (en attente d'horloge live)

    def _charger(self, chemin: Path) -> dict:
        try:
            return json.loads(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _sauver_fichier(self, chemin: Path, obj: dict):
        Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(chemin).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, chemin)

    def _sauver(self):
        self._sauver_fichier(self.path, self.etat)

    def _sauver_attente(self):
        self._sauver_fichier(self.attente_path, self.attente)

    def figer(self, candidate_id: str, *, freeze_exchange_ts, meta: dict | None = None) -> dict:
        """Fige un candidat (immuable). GR/micro-fix point 1 : on NE GÈLE JAMAIS avec un freeze_exchange_ts <= 0
        (horloge live invalide) — le candidat passe alors en WAITING_FOR_LIVE_CLOCK (aucun gel). Si déjà figé,
        renvoie l'entrée existante SANS changer son freeze."""
        if candidate_id in self.etat:
            return self.etat[candidate_id]
        if freeze_exchange_ts is None or float(freeze_exchange_ts) <= 0.0:
            self.attente[candidate_id] = {"candidate_id": candidate_id, "statut": "WAITING_FOR_LIVE_CLOCK",
                                          "meta": meta or {}, "maj_ms": int(time.time() * 1000)}
            self._sauver_attente()
            return self.attente[candidate_id]                # PAS de gel : horloge live absente
        self.etat[candidate_id] = {
            "candidate_id": candidate_id, "freeze_exchange_ts": float(freeze_exchange_ts),
            "last_forward_event_id": None, "n_episodes_live": 0, "duree_live_ms": 0.0,
            "pnl_live_bps": 0.0, "roi_live_pct": 0.0, "pic_live_bps": 0.0, "dd_live_bps": 0.0,
            "vus": [], "positif_live": False, "meta": meta or {}, "fige_ms": int(time.time() * 1000)}
        if candidate_id in self.attente:                     # promu de l'attente au gel (horloge live devenue valide)
            self.attente.pop(candidate_id, None)
            self._sauver_attente()
        self._sauver()
        return self.etat[candidate_id]

    def episodes_admissibles(self, candidate_id: str, episodes) -> list:
        """Épisodes utilisables pour CE candidat = STRICTEMENT après SON freeze_exchange_ts (garantie dure)."""
        c = self.etat.get(candidate_id)
        if not c:
            return []
        return filtrer_apres_freeze(episodes, c["freeze_exchange_ts"])

    def suivre(self, candidate_id: str, *, paires=None, nets_live=None, last_event_id=None,
               maintenant_ms=None, cap_vus: int = 5000) -> dict | None:
        """Suivi live CUMULATIF (FX/GR-1). N'ajoute QUE les NOUVEAUX épisodes : `paires` = [(episode_id, net_bps)]
        (dédup par episode_id via `vus`) ; `nets_live` = nets bruts sans id (repli, comptés comme nouveaux). Les
        compteurs PnL/ROI/DD/n_episodes CUMULENT sur plusieurs cycles ; le drawdown est mesuré sur la courbe
        cumulée, épisode par épisode. Un cycle SANS nouvel épisode ne remet JAMAIS les compteurs à zéro."""
        c = self.etat.get(candidate_id)
        if not c:
            return None
        vus = set(c.get("vus") or [])
        ajout = []
        dernier_id = c.get("last_forward_event_id")
        if paires:
            for eid, net in paires:
                if eid is not None and eid in vus:            # dédup par episode_id (jamais compté deux fois)
                    continue
                if not isinstance(net, (int, float)):
                    continue
                ajout.append(float(net))
                if eid is not None:
                    vus.add(eid)
                    dernier_id = eid
        elif nets_live:
            ajout = [float(x) for x in nets_live if isinstance(x, (int, float))]
        if ajout:                                             # CUMUL (repart de l'état persistant, jamais de 0)
            cum = float(c.get("pnl_live_bps", 0.0))
            pic = float(c.get("pic_live_bps", 0.0))
            dd = float(c.get("dd_live_bps", 0.0))
            for net in ajout:
                cum += net
                pic = max(pic, cum)
                dd = max(dd, pic - cum)
            c["pnl_live_bps"] = round(cum, 4)
            c["pic_live_bps"] = round(pic, 4)
            c["dd_live_bps"] = round(dd, 4)
            c["roi_live_pct"] = round(cum / 100.0, 4)         # bps -> % (1 bps = 0.01 %)
            c["n_episodes_live"] = int(c.get("n_episodes_live", 0)) + len(ajout)
            c["positif_live"] = bool(c["n_episodes_live"] > 0 and cum > 0)
            c["vus"] = list(vus)[-int(cap_vus):]              # borné (24/7) : on garde les plus récents
        # last_event_id / durée : mis à jour même sans nouvel épisode, MAIS sans toucher aux compteurs (pas de reset)
        if last_event_id is not None:
            c["last_forward_event_id"] = last_event_id
        elif dernier_id is not None:
            c["last_forward_event_id"] = dernier_id
        if maintenant_ms is not None:
            c["duree_live_ms"] = round(float(maintenant_ms) - c["freeze_exchange_ts"], 2)
        self._sauver()
        return c

    def candidats(self) -> list:
        return list(self.etat.values())

    def resume(self) -> dict:
        cs = self.candidats()
        return {"n_candidats": len(cs), "n_positifs_live": sum(1 for c in cs if c.get("positif_live")),
                "n_avec_donnee_live": sum(1 for c in cs if (c.get("n_episodes_live") or 0) > 0),
                "n_attente_horloge_live": len(self.attente)}


__all__ = ["RegistreCandidatsLive", "filtrer_apres_freeze"]
