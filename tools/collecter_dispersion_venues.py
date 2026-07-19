"""COLLECTEUR DE DISPERSION DE FUNDING ENTRE VENUES — la dernière piste ouverte.

Protocole et critères de rejet : `docs/audit/PROTOCOLE_CROSS_VENUE.md`, écrit AVANT la première
donnée. Ce collecteur ne juge rien : il OBSERVE et ENREGISTRE. Le verdict est rendu par
`tools/mesurer_dispersion_venues.py`, contre des barres fixées à l'avance.

CE QU'IL FAIT
-------------
Toutes les N secondes, il lit le funding de chaque coin sur les deux venues et écrit une ligne
horodatée dans `runtime/data/dispersion_venues.jsonl` :

    {"ts": ..., "coin": "BTC", "hl_bps_h": 0.125, "bin_bps_h": 0.42, "dispersion_bps_h": 0.295}

PIÈGE D'UNITÉ, DÉJÀ PAYÉ ICI (13/07 : « 38 % APR qui étaient l'intervalle de funding »)
--------------------------------------------------------------------------------------
**Hyperliquid paie le funding PAR HEURE. Binance le paie PAR 8 HEURES.** Comparer les deux taux
bruts, c'est se tromper d'un facteur 8 — et 8× sur un funding, ça transforme une piste morte en
pépite imaginaire. La conversion est faite ICI, une seule fois, et elle est testée.

CE QU'IL N'INVENTE PAS
----------------------
Un funding illisible sur une venue -> la ligne n'est PAS écrite. Pas de zéro de remplissage, pas
de report de la valeur précédente : un trou honnête vaut mieux qu'une donnée fabriquée, parce
qu'une dispersion calculée contre un zéro inventé serait énorme et fausse.

READ-ONLY : deux endpoints publics. Aucune clé, aucune signature, aucun ordre. Binance n'est
qu'une SOURCE DE PRIX — Hyperliquid reste la seule venue des décisions paper.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

URL_HL = "https://api.hyperliquid.xyz/info"
URL_BINANCE = "https://fapi.binance.com/fapi/v1/premiumIndex"

#: 🔴 Binance publie un funding par 8 h. HL paie par heure. Facteur 8, une seule fois, ici.
HEURES_PAR_PERIODE_BINANCE = 8.0

SORTIE = Path("runtime") / "data" / "dispersion_venues.jsonl"
COINS_DEFAUT = "BTC,ETH,SOL,HYPE,AVAX,LINK,DOGE,SUI,ARB,OP"
INTERVALLE_S_DEFAUT = 300.0


def _get(url: str, *, timeout_s: float = 12.0):
    with urllib.request.urlopen(url, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _post(url: str, charge: dict, *, timeout_s: float = 12.0):
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(url, data=corps,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310
        return json.loads(rep.read().decode("utf-8"))


def funding_hyperliquid() -> dict[str, float]:
    """{coin: funding en bps/HEURE}. HL publie deja un taux horaire (fraction)."""
    data = _post(URL_HL, {"type": "metaAndAssetCtxs"})
    if not isinstance(data, list) or len(data) < 2:
        return {}
    univers = (data[0] or {}).get("universe") or []
    ctxs = data[1] or []
    out: dict[str, float] = {}
    for meta, ctx in zip(univers, ctxs):
        try:
            coin = str(meta.get("name") or "").upper()
            f = float((ctx or {}).get("funding"))
        except (TypeError, ValueError, AttributeError):
            continue
        if coin and f == f:                       # NaN écarté
            out[coin] = f * 1e4                   # fraction/h -> bps/h
    return out


def funding_binance() -> dict[str, float]:
    """{coin: funding en bps/HEURE}. ⚠️ Binance publie un taux PAR 8 H -> on divise par 8."""
    data = _get(URL_BINANCE)
    if not isinstance(data, list):
        return {}
    out: dict[str, float] = {}
    for row in data:
        try:
            sym = str(row.get("symbol") or "")
            if not sym.endswith("USDT"):
                continue
            f8 = float(row.get("lastFundingRate"))
        except (TypeError, ValueError, AttributeError):
            continue
        if f8 != f8:
            continue
        coin = sym[:-4].upper()
        out[coin] = (f8 / HEURES_PAR_PERIODE_BINANCE) * 1e4          # fraction/8h -> bps/h
    return out


def une_passe(root: Path, coins: list[str]) -> tuple[int, int]:
    """(lignes écrites, coins comparables). Une venue muette -> 0 ligne, jamais d'invention."""
    try:
        hl, binance = funding_hyperliquid(), funding_binance()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0, 0
    if not hl or not binance:
        return 0, 0

    maintenant = time.time()
    lignes = []
    for coin in coins:
        c = coin.upper().strip()
        a, b = hl.get(c), binance.get(c)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue                              # coin absent d'une venue -> on n'ecrit RIEN
        lignes.append({"ts": round(maintenant, 3), "coin": c,
                       "hl_bps_h": round(float(a), 6), "bin_bps_h": round(float(b), 6),
                       "dispersion_bps_h": round(abs(float(a) - float(b)), 6),
                       "venue_haute": "BINANCE" if b > a else "HL",
                       "read_only": True, "real_execution": False})
    if not lignes:
        return 0, 0
    chemin = root / SORTIE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    try:
        with chemin.open("a", encoding="utf-8") as fh:
            for l in lignes:
                fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    except OSError:
        return 0, len(lignes)
    return len(lignes), len(lignes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur de dispersion de funding (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--coins", default=COINS_DEFAUT)
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)

    root = Path(a.root)
    coins = [c for c in (a.coins or "").split(",") if c.strip()]
    print("[venues] collecteur demarre — %d coin(s) suivis, toutes les %.0f s"
          % (len(coins), a.intervalle), flush=True)
    total = 0
    while True:
        n, comparables = une_passe(root, coins)
        total += n
        if comparables:
            print("[venues] %s  ecrits=%d  cumul=%d  (%d coins comparables sur les 2 venues)"
                  % (time.strftime("%H:%M:%S"), n, total, comparables), flush=True)
        else:
            print("[venues] %s  aucune paire comparable ce tick (venue muette ou coin absent) — "
                  "rien ecrit, rien invente" % time.strftime("%H:%M:%S"), flush=True)
        if a.une_fois:
            return 0
        time.sleep(max(30.0, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
