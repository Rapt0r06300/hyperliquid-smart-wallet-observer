"""ALPHA P41 — FORWARD FROZEN service : tout candidat OOS valide entre en forward IMMUABLE. Aucun retune.

Config + hash scellés à la promotion. On mesure ensuite en continu PnL / coût / fill / capacité / drift, mais
on NE re-optimise JAMAIS la config (immuable). Toute tentative de modifier la config scellée est refusée.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class ForwardFrozen:
    """Registre de candidats forward scellés + observations continues (append-only)."""

    def __init__(self) -> None:
        self._scelles: dict[str, dict[str, Any]] = {}
        self._obs: dict[str, list[dict[str, Any]]] = {}

    def promouvoir(self, candidat_id: str, config: Mapping[str, Any]) -> dict[str, Any]:
        """Scelle la config d'un candidat. Idempotent : re-promouvoir la MÊME config est ok ; une DIFFÉRENTE est refusée."""
        h = hashlib.sha1(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]
        cid = str(candidat_id)
        if cid in self._scelles and self._scelles[cid]["config_hash"] != h:
            raise ValueError("retune interdit : config forward scellee pour %s" % cid)
        self._scelles.setdefault(cid, {"config": dict(config), "config_hash": h})
        self._obs.setdefault(cid, [])
        return {"candidat": cid, "config_hash": h, "scelle": True}

    def observer(self, candidat_id: str, mesure: Mapping[str, Any]) -> None:
        """Ajoute une mesure forward (PnL/cost/fill/capacity/drift). N'altère jamais la config."""
        if str(candidat_id) not in self._scelles:
            raise KeyError("candidat non scelle : %s" % candidat_id)
        self._obs[str(candidat_id)].append(dict(mesure))

    def etat(self, candidat_id: str) -> dict[str, Any]:
        cid = str(candidat_id)
        obs = self._obs.get(cid, [])
        nets = [o["net_bps"] for o in obs if isinstance(o.get("net_bps"), (int, float))]
        return {"candidat": cid, "config_hash": self._scelles.get(cid, {}).get("config_hash"),
                "n_observations": len(obs), "net_moyen_forward_bps": round(sum(nets) / len(nets), 4) if nets else None}


__all__ = ["ForwardFrozen"]
