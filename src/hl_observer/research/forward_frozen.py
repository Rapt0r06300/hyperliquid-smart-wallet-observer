"""ALPHA P41 / FIX-47 — FORWARD FROZEN PERSISTANT : candidat OOS valide → forward IMMUABLE, journal scellé.

Correction de P41 (qui n'existait qu'en mémoire) : l'état est PERSISTÉ dans un journal JSONL append-only,
rechargé au démarrage (reprise process-safe). Config + hash scellés à la promotion ; toute tentative de
retune (même candidat, config différente) est REFUSÉE. Les observations continues (PnL/cost/fill/capacity/
drift) sont ajoutées en append-only et jamais réécrites. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def _hash_config(config: Mapping[str, Any]) -> str:
    return hashlib.sha1(json.dumps(config, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


class ForwardFrozen:
    """Registre forward scellé, persistant (JSONL). `path=None` → mémoire seule (tests). Reprise via rechargement."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._scelles: dict[str, dict[str, Any]] = {}
        self._obs: dict[str, list[dict[str, Any]]] = {}
        if path:
            self._recharger()

    def _recharger(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:      # type: ignore[arg-type]
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cid = str(r.get("candidat"))
                    if r.get("type") == "SEAL":
                        self._scelles[cid] = {"config": r.get("config"), "config_hash": r.get("config_hash")}
                        self._obs.setdefault(cid, [])
                    elif r.get("type") == "OBS":
                        self._obs.setdefault(cid, []).append(r.get("mesure", {}))
        except FileNotFoundError:
            pass

    def _append(self, rec: Mapping[str, Any]) -> None:
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def promouvoir(self, candidat_id: str, config: Mapping[str, Any]) -> dict[str, Any]:
        """Scelle la config (persistée). Re-promouvoir la MÊME config est idempotent ; une DIFFÉRENTE = refus."""
        cid = str(candidat_id)
        h = _hash_config(config)
        if cid in self._scelles and self._scelles[cid]["config_hash"] != h:
            raise ValueError("retune interdit : config forward scellée pour %s" % cid)
        if cid not in self._scelles:
            self._scelles[cid] = {"config": dict(config), "config_hash": h}
            self._obs.setdefault(cid, [])
            self._append({"type": "SEAL", "candidat": cid, "config": dict(config), "config_hash": h})
        return {"candidat": cid, "config_hash": h, "scelle": True, "persistant": self.path is not None}

    def observer(self, candidat_id: str, mesure: Mapping[str, Any]) -> None:
        """Ajoute une mesure forward (append-only, persistée). N'altère jamais la config."""
        cid = str(candidat_id)
        if cid not in self._scelles:
            raise KeyError("candidat non scellé : %s" % cid)
        self._obs[cid].append(dict(mesure))
        self._append({"type": "OBS", "candidat": cid, "mesure": dict(mesure)})

    def etat(self, candidat_id: str) -> dict[str, Any]:
        cid = str(candidat_id)
        obs = self._obs.get(cid, [])
        nets = [o["net_bps"] for o in obs if isinstance(o.get("net_bps"), (int, float))]
        return {"candidat": cid, "config_hash": self._scelles.get(cid, {}).get("config_hash"),
                "n_observations": len(obs),
                "net_moyen_forward_bps": round(sum(nets) / len(nets), 4) if nets else None}

    def candidats(self) -> list[str]:
        return sorted(self._scelles)


__all__ = ["ForwardFrozen"]
