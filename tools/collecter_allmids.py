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

URL_HL = "https://api.hyperliquid.xyz/info"
SORTIE = Path("runtime") / "data" / "hl_allmids.json"
INTERVALLE_S_DEFAUT = 15.0


def parser_allmids(rep: Any) -> dict[str, float]:
    """{coin: mid_float} depuis la réponse allMids. HL renvoie {coin: "prix_str"} (parfois enveloppé
    dans {'mids': {...}}). Prix illisible / <= 0 → ignoré (jamais un prix inventé)."""
    src = rep.get("mids") if isinstance(rep, dict) and "mids" in rep else rep
    out: dict[str, float] = {}
    if isinstance(src, dict):
        for c, v in src.items():
            try:
                px = float(v)
            except (TypeError, ValueError):
                continue
            coin = str(c or "").upper()
            if coin and px > 0:
                out[coin] = px
    return out


def _post_allmids(*, timeout_s: float = 8.0) -> Any:
    corps = json.dumps({"type": "allMids"}).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def ecrire_cache(root: Path, mids: dict[str, float]) -> int:
    """Écrit {ts_ms, n, mids} de façon ATOMIQUE (tmp → replace). Rend le nombre de coins."""
    dest = root / SORTIE
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts_ms": int(time.time() * 1000), "n": len(mids), "source": "hyperliquid allMids (public, read-only)",
               "mids": mids}
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return len(mids)


def une_passe(root: Path, *, post_allmids=_post_allmids) -> int:
    """Un fetch allMids → cache. Rend le nombre de coins (0 si réseau KO)."""
    try:
        mids = parser_allmids(post_allmids())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0
    if not mids:
        return 0
    return ecrire_cache(root, mids)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur allMids HL (lecture seule, tous-coins).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    echecs = 0
    while True:
        try:
            n = une_passe(root)
            if n:
                echecs = 0
                print("[allmids] %s  coins=%d  -> %s" % (time.strftime("%H:%M:%S"), n, SORTIE), flush=True)
            else:
                echecs += 1
                d = CF.backoff_jitter(echecs)
                print("[allmids] fetch vide/KO — backoff %.1fs" % d, flush=True)
                time.sleep(d)
        except Exception as exc:  # noqa: BLE001 — on ne meurt pas
            echecs += 1
            d = CF.backoff_jitter(echecs)
            print("[allmids] erreur (%s) — backoff %.1fs" % (str(exc)[:60], d), flush=True)
            time.sleep(d)
        if a.une_fois:
            return 0
        time.sleep(max(10.0, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
