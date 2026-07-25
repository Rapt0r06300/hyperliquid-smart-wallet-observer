"""COLLECTEUR ASSET-CTX (OI_PREMIUM_CROWDING_V1, Flo 25/07) — archive l'historique par coin nécessaire
aux variantes OI/premium : open interest, funding, premium mark/oracle, volume 24h, impact prices.

READ-ONLY : un seul endpoint public `metaAndAssetCtxs` (comme `collecter_overshoots`). Aucune clé, aucune
signature, aucun ordre. Archive append-only dans `runtime/data/asset_ctx_tape.jsonl` (préservé — jamais
écrasé), + un heartbeat. Le ΔOI se calcule au backtest depuis la série (pas d'état fragile ici).

Poster injectable -> testable sans réseau. Le collecteur ne DÉCIDE rien : il archive des faits.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

URL_INFO = "https://api.hyperliquid.xyz/info"
TAPE = Path("runtime") / "data" / "asset_ctx_tape.jsonl"       # HISTORIQUE append-only (préservé)
HEARTBEAT = Path("runtime") / "data" / "asset_ctx_heartbeat.json"
POLL_S_DEFAUT = 30.0                                            # 1 snapshot / 30 s suffit pour OI/premium


def _post_info(charge: dict, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(URL_INFO, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante publique)
        return json.loads(rep.read().decode("utf-8"))


def parser_ctx_complet(payload: Any) -> dict[str, dict]:
    """[meta, contextes] -> {COIN: {oi, funding, mark, oracle, premium_bps, vol24h, impact_bid, impact_ask}}.
    Champ manquant/illisible -> coin écarté (jamais une valeur inventée : vérité des données)."""
    out: dict[str, dict] = {}
    try:
        meta, ctxs = payload[0], payload[1]
        univers = meta["universe"]
    except (TypeError, KeyError, IndexError):
        return out
    if not isinstance(ctxs, list) or not isinstance(univers, list):
        return out
    for i, actif in enumerate(univers):
        if i >= len(ctxs) or not isinstance(actif, dict) or not isinstance(ctxs[i], dict):
            continue
        c = ctxs[i]
        nom = str(actif.get("name") or "").upper()
        try:
            oracle = float(c["oraclePx"])
            mark = float(c.get("markPx") or oracle)
        except (KeyError, TypeError, ValueError):
            continue
        if not nom or oracle <= 0:
            continue
        def _f(k):
            try:
                return float(c[k])
            except (KeyError, TypeError, ValueError):
                return None
        imp = c.get("impactPxs") or []
        try:
            ib = float(imp[0]) if len(imp) >= 1 else None
            ia = float(imp[1]) if len(imp) >= 2 else None
        except (TypeError, ValueError):
            ib = ia = None
        out[nom] = {"oi": _f("openInterest"), "funding": _f("funding"), "mark": mark, "oracle": oracle,
                    "premium_bps": round((mark - oracle) / oracle * 1e4, 3),
                    "vol24h": _f("dayNtlVlm"), "impact_bid": ib, "impact_ask": ia}
    return out


def une_passe(root: Path, *, poster: Callable[..., Any] = _post_info, now: float | None = None) -> int:
    """Un snapshot ctx -> archive 1 ligne par coin. Rend le nb de coins archivés (0 si réseau KO)."""
    t = now if now is not None else time.time()
    try:
        ctxs = parser_ctx_complet(poster({"type": "metaAndAssetCtxs"}))
    except Exception:
        return 0
    if not ctxs:
        return 0
    p = root / TAPE
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for coin, d in ctxs.items():
            f.write(json.dumps({"ts_ms": int(t * 1000), "coin": coin, **d,
                                "source": "metaAndAssetCtxs", "read_only": True, "real_execution": False},
                               ensure_ascii=False) + "\n")
    (root / HEARTBEAT).write_text(json.dumps({"ts_ms": int(t * 1000), "coins": len(ctxs)}), encoding="utf-8")
    return len(ctxs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collecteur asset-ctx (OI/premium/funding/volume), lecture seule.")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--poll-s", type=float, default=POLL_S_DEFAUT)
    ap.add_argument("--une-passe", action="store_true", help="un seul snapshot puis sort")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.une_passe:
        n = une_passe(root)
        print("[asset_ctx] 1 passe : %d coins archivés" % n, flush=True)
        return 0
    print("[asset_ctx] démarrage boucle poll=%.0fs (read-only)" % a.poll_s, flush=True)
    while True:
        try:
            n = une_passe(root)
            print("[asset_ctx] %d coins archivés" % n, flush=True)
        except Exception as e:  # noqa: BLE001 (une boucle collecteur ne meurt jamais sur une passe)
            print("[asset_ctx] passe KO: %s" % e, flush=True)
        time.sleep(a.poll_s)


if __name__ == "__main__":
    raise SystemExit(main())
