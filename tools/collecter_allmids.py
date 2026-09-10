"""COLLECTEUR allMids — prix HL frais TOUS-COINS pour Copy-Vaults.

POURQUOI (23/07)
----------------
Le signal Copy-Vaults détecte un changement d'exposition d'un vault suivi PAR COIN. Mais les vaults
tradent ~100 coins (0G, AAVE, ... ZRO) alors que le flux BBO synchro n'en couvre que 8 (BTC/ETH/SOL/
INJ/DASH/AVAX/LINK/NEO). Sans prix HL exécutable pour les 92 autres, la plupart des moves copiables
sont refusés (PRIX_NON_EXECUTABLE_HL). `allMids` est UN SEUL appel public qui renvoie le mid de TOUS
les coins → on le persiste ici pour que le tick copy-vault (process séparé) le lise.

RELIABLE, PAS DU HAMMERING
--------------------------
Un seul POST {"type":"allMids"} par tick (pas par coin) → coût de rate minuscule, on peut rafraîchir
souvent (10-20 s) → mids frais. Limiteur + backoff+jitter (socle collecte_fiable). Chaque écriture
est estampillée (ts_ms). Écriture atomique (tmp → replace) pour que le lecteur ne voie jamais un
fichier tronqué.

READ-ONLY / PAPER-ONLY : lire allMids public n'est pas passer un ordre. Aucune signature, aucune clé.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import heartbeat_collecteur as HB  # noqa: E402

from hl_observer.collection import collecte_fiable as CF  # noqa: E402

URL_HL = "https://api.hyperliquid.xyz/info"
SORTIE = Path("runtime") / "data" / "hl_allmids.json"
TAPE = Path("runtime") / "data" / "hl_allmids_tape.jsonl"   # HISTORIQUE (pour mesurer l'edge forward de copie)
TAPE_INTERVALLE_S = 60.0                                    # on n'archive qu'1 point/min (le cache reste à 15 s)
INTERVALLE_S_DEFAUT = 15.0


def parser_allmids(rep: Any) -> dict[str, float]:
    """{coin: mid_float} depuis la réponse allMids. HL renvoie {coin: "prix_str"} (parfois enveloppé
    dans {'mids': {...}}). Prix illisible / <= 0 → ignoré (jamais un prix inventé)."""
    src = rep.get("mids") if isinstance(rep, dict) and "mids" in rep else rep
    out: dict[str, float] = {}
    if isinstance(src, dict):
        for c, v in src.items():
            if isinstance(v, bool):
                continue
            try:
                px = float(v)
            except (TypeError, ValueError):
                continue
            coin = str(c or "").upper()
            if coin and math.isfinite(px) and px > 0:
                out[coin] = px
    return out


def _post_allmids(*, timeout_s: float = 8.0) -> Any:
    corps = json.dumps({"type": "allMids"}).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _cache_sample_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ecrire_cache(
    root: Path,
    mids: dict[str, float],
    *,
    fetched_at_ms: int | None = None,
    transport_latency_ms: float = 0.0,
    data_mode: str = "LIVE",
) -> int:
    """Écrit {ts_ms, n, mids} de façon ATOMIQUE (tmp → replace). Rend le nombre de coins."""
    dest = root / SORTIE
    dest.parent.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000) if fetched_at_ms is None else int(fetched_at_ms)
    payload = {
        "ts_ms": timestamp,
        "n": len(mids),
        "source": "hyperliquid allMids (public, read-only)",
        "mids": mids,
    }
    payload["coverage_capture"] = {
        "schema_version": "hypersmart.allmids_coverage_capture.v1",
        "source_id": "hyperliquid-info-allmids",
        "endpoint": URL_HL,
        "request_type": "allMids",
        "fetched_at_ms": timestamp,
        "transport_latency_ms": round(float(transport_latency_ms), 6),
        "data_mode": str(data_mode),
        "sample_hash": _cache_sample_hash(payload),
        "paper_read_only": True,
        "real_execution": False,
    }
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return len(mids)


def ecrire_tape(root: Path, mids: dict[str, float]) -> None:
    """Append UN point (ts + mids compacts) à la tape historique — la matière du backtest d'edge."""
    dest = root / TAPE
    dest.parent.mkdir(parents=True, exist_ok=True)
    ligne = json.dumps({"ts_ms": int(time.time() * 1000), "mids": {c: round(p, 8) for c, p in mids.items()}},
                       ensure_ascii=False)
    with dest.open("a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def une_passe(root: Path, *, post_allmids=_post_allmids, archiver_tape: bool = False) -> int:
    """Un fetch allMids → cache courant (+ tape historique si `archiver_tape`). Rend le nb de coins (0 si KO)."""
    try:
        started = time.perf_counter()
        mids = parser_allmids(post_allmids())
        latency_ms = (time.perf_counter() - started) * 1000.0
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0
    if not mids:
        return 0
    n = ecrire_cache(
        root,
        mids,
        fetched_at_ms=int(time.time() * 1000),
        transport_latency_ms=latency_ms,
        data_mode="LIVE" if post_allmids is _post_allmids else "TEST_FIXTURE",
    )
    HB.battre(root, "allmids-collector", pid=os.getppid(), n_ecrites=1,
              souscription_ack=True, note=f"{n} real allMids prices")
    if archiver_tape:
        ecrire_tape(root, mids)
    return n


def _tape_due(root: Path) -> bool:
    """La tape est-elle « en retard » ? Décision basée sur le DERNIER ts de la tape (robuste même en
    --une-fois relancé toutes les 15 s par boucle_collecteur : on n'archive qu'1 point/min)."""
    p = root / TAPE
    try:
        with p.open("rb") as f:
            f.seek(0, 2)
            taille = f.tell()
            f.seek(max(0, taille - 4096))
            derniere = f.read().decode("utf-8", "ignore").splitlines()[-1]
        ts = float(json.loads(derniere).get("ts_ms") or 0)
    except (OSError, ValueError, IndexError):
        return True
    return (time.time() * 1000 - ts) >= TAPE_INTERVALLE_S * 1000


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur allMids HL (lecture seule, tous-coins).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    echecs = 0.0
    while True:
        try:
            n = une_passe(root, archiver_tape=_tape_due(root))
            if n:
                echecs = 0
                print(
                    f"[allmids] {time.strftime('%H:%M:%S')}  coins={n}  -> {SORTIE}",
                    flush=True,
                )
            else:
                echecs += 1
                d = CF.backoff_jitter(echecs)
                print(f"[allmids] fetch vide/KO — backoff {d:.1f}s", flush=True)
                time.sleep(d)
        except Exception as exc:  # noqa: BLE001 — on ne meurt pas
            echecs += 1
            d = CF.backoff_jitter(echecs)
            print(
                f"[allmids] erreur ({str(exc)[:60]}) — backoff {d:.1f}s",
                flush=True,
            )
            time.sleep(d)
        if a.une_fois:
            return 0
        time.sleep(max(10.0, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
