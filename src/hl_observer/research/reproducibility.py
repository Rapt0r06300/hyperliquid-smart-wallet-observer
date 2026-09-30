"""ALPHA P57 — REPRODUCTIBILITÉ : empreinte complète par trial (même trial → même résultat).

Chaque trial garde code SHA, dataset hash, config hash, seed, version Python/deps, timestamps début/fin.
Deux trials avec la même empreinte (hors timestamps) doivent produire le même résultat. Pur, 0 réseau.
"""
from __future__ import annotations

import hashlib
import platform
import sys
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def empreinte_repro(*, code_sha: str = UNMEASURABLE, dataset_hash: str = UNMEASURABLE,
                    config_hash: str = UNMEASURABLE, seed: Any = None,
                    start_ts_ms: Any = None, end_ts_ms: Any = None) -> dict[str, Any]:
    """Empreinte de repro d'un trial. `repro_key` = hash déterministe des champs HORS timestamps."""
    py = "%d.%d.%d" % sys.version_info[:3]
    base = "|".join(str(x) for x in (code_sha, dataset_hash, config_hash, seed, py, platform.machine()))
    repro_key = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return {"code_sha": code_sha, "dataset_hash": dataset_hash, "config_hash": config_hash,
            "seed": seed, "python": py, "arch": platform.machine(),
            "start_ts_ms": start_ts_ms, "end_ts_ms": end_ts_ms, "repro_key": repro_key}


def meme_repro(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Deux empreintes sont reproductiblement identiques si même repro_key (timestamps ignorés)."""
    return a.get("repro_key") == b.get("repro_key")


__all__ = ["empreinte_repro", "meme_repro", "UNMEASURABLE"]
