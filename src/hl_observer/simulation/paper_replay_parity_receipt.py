"""Receipt de parité paper↔replay — empreinte scellée données+config+métriques.

Q-153 : avant toute promotion de config, le labo scelle un receipt prouvant que
la config testée en replay reproduit le PnL paper observé. Le receipt contient :
  1. hash SHA-256 des données (fills, marks, candidates)
  2. hash SHA-256 de la config (paramètres gelés)
  3. métriques clés (PnL net, Sharpe, max DD, winrate, n trades)
  4. timestamp de création (UTC)

Le receipt est un dict JSON sérialisable et immuable. Le runtime peut le relire
pour vérifier qu'il utilise bien la config validée (config hash match).

PAPER / READ-ONLY / FAIL-CLOSED — aucune donnée fabriquée.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Sequence

from hl_observer.ops.echec_silencieux import noter as _noter_echec


@dataclass(frozen=True, slots=True)
class ParityReceipt:
    data_hash: str
    config_hash: str
    pnl_net_usdt: float
    sharpe: float
    max_dd_usdt: float
    winrate: float
    n_trades: int
    created_utc: float
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def integrity_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_rows(rows: Sequence[dict]) -> str:
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True, ensure_ascii=True).encode("utf-8"))
    return h.hexdigest()


def _hash_config(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seal_receipt(
    *,
    data_rows: Sequence[dict],
    config: dict,
    pnl_net_usdt: float,
    sharpe: float,
    max_dd_usdt: float,
    winrate: float,
    n_trades: int,
    label: str = "",
) -> ParityReceipt:
    return ParityReceipt(
        data_hash=_hash_rows(data_rows),
        config_hash=_hash_config(config),
        pnl_net_usdt=round(float(pnl_net_usdt), 4),
        sharpe=round(float(sharpe), 4),
        max_dd_usdt=round(float(max_dd_usdt), 4),
        winrate=round(float(winrate), 4),
        n_trades=int(n_trades),
        created_utc=time.time(),
        label=str(label),
    )


def save_receipt(receipt: ParityReceipt, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.to_dict()
    payload["_integrity"] = receipt.integrity_hash()
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load_receipt(path: str | Path) -> ParityReceipt | None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        raw.pop("_integrity", None)
        return ParityReceipt(**{k: v for k, v in raw.items() if k in ParityReceipt.__dataclass_fields__})
    except Exception as _exc:
        _noter_echec("simulation/paper_replay_parity_receipt.py:load", _exc)
        return None


def verify_config_match(receipt: ParityReceipt, current_config: dict) -> bool:
    return receipt.config_hash == _hash_config(current_config)


__all__ = [
    "ParityReceipt",
    "seal_receipt",
    "save_receipt",
    "load_receipt",
    "verify_config_match",
]
