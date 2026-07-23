"""BACKFILL CANDLES 5m SUR LES COINS DE VAULTS (rectif Flo 23/07) — débloque la couverture prix.

POURQUOI
--------
La mesure OOS de l'edge de copie exige un prix historique pour CHAQUE coin tradé par les vaults, sur
TOUTE la période des fills (~335 h). Les candles 1m plafonnent à ~83 h (candleSnapshot ≤ 5000 bougies) ;
les vieux candles ne couvrent que 12 majors. En **5m**, 5000 bougies = **416 h** : un seul appel/coin
couvre les 335 h. Ce backfill lit les coins réellement tradés (depuis les fills), tire leurs candles 5m
sur la fenêtre des fills, et écrit `runtime/history/candles_5m.jsonl`. On MESURE la couverture obtenue,
on ne la promet pas (troncature détectée si une réponse plafonne à 5000).

Lecture seule (candleSnapshot public). 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import collecte_fiable as CF  # noqa: E402
from hl_observer.collection import candle_backfill as CB  # noqa: E402

URL_HL = "https://api.hyperliquid.xyz/info"
FILLS = Path("runtime") / "data" / "vault_fills.jsonl"
SORTIE = Path("runtime") / "history" / "candles_5m.jsonl"
CAP_CANDLES = 5000               # candleSnapshot plafonne à ~5000 bougies (limite officielle)


def coins_et_fenetre(root: Path) -> tuple[list[str], int, int]:
    """(coins tradés par les vaults, t0_ms, t1_ms) depuis les fills backfillés."""
    coins: dict[str, None] = {}
    tmin, tmax = 9 << 60, 0
    try:
        for l in (root / FILLS).read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(l)
            except ValueError:
                continue
            c = str(d.get("coin") or "").upper()
            t = int(d.get("ts_ms") or 0)
            if c:
                coins.setdefault(c, None)
            if t:
                tmin, tmax = min(tmin, t), max(tmax, t)
    except OSError:
        return [], 0, 0
    return list(coins), (tmin if tmax else 0), tmax


def _post_candles(coin: str, intervalle: str, a: int, b: int, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps({"type": "candleSnapshot",
                        "req": {"coin": coin, "interval": intervalle, "startTime": int(a), "endTime": int(b)}}).encode()
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def backfill_un_coin(coin: str, a: int, b: int, *, intervalle: str = "5m", limiteur: CF.Limiteur,
                     poster=_post_candles) -> tuple[list[dict], bool]:
    """(bougies propres du coin, tronque?). Tronque si une réponse atteint le cap 5000."""
    limiteur.attente()
    try:
        payload = poster(coin, intervalle, a, b)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return [], False
    bougies = CB.parser_bougies(coin, payload)
    tronque = len(bougies) >= CAP_CANDLES
    return [x.as_dict() for x in CB.dedupliquer(bougies)], tronque


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill candles 5m sur les coins de vaults (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", default="5m")
    p.add_argument("--une-fois", action="store_true", default=True)
    a = p.parse_args(argv)
    root = Path(a.root)
    coins, t0, t1 = coins_et_fenetre(root)
    if not coins:
        print("[candles-vaults] aucun coin (pas de fills backfilles) — rien a faire", flush=True)
        return 0
    limiteur = CF.Limiteur(0.2)
    tous: list[dict] = []
    tronques: list[str] = []
    for c in coins:
        bougies, tronque = backfill_un_coin(c, t0, t1, intervalle=a.intervalle, limiteur=limiteur)
        tous.extend(bougies)
        if tronque:
            tronques.append(c)
    (root / SORTIE).parent.mkdir(parents=True, exist_ok=True)
    (root / SORTIE).write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in tous), encoding="utf-8")
    print("[candles-vaults] %d coins, %d bougies %s ecrites -> %s%s"
          % (len(coins), len(tous), a.intervalle, SORTIE,
             (" | TRONQUES(cap5000): %s" % ",".join(tronques[:10])) if tronques else ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
