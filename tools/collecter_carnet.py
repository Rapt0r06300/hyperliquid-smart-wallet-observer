"""Read-only HL/Binance top-of-book collector with certified cross-venue provenance.

The collector keeps historical diagnostic fields but now also records the exact
Binance perpetual mapping, top-5 raw depth and the receive time of each venue.
Only exact mapping + bounded measured skew can later certify economic evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
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
from hl_observer.config.cross_venue_instruments import (  # noqa: E402
    MAPPING_SCHEMA_VERSION,
    binance_perp_symbol,
    mapping_record,
)
from hl_observer.backtesting.cross_venue_certified import (  # noqa: E402
    MAX_VENUE_SKEW_MS,
    SOURCE_MODE as CERTIFIED_SOURCE_MODE,
)

URL_HL = "https://api.hyperliquid.xyz/info"
URL_BIN_DEPTH = "https://fapi.binance.com/fapi/v1/depth"
SORTIE = Path("runtime") / "data" / "carnet_venues.jsonl"
DISPERSION = Path("runtime") / "data" / "dispersion_venues.jsonl"
N_COINS_PRIORITAIRES = 15
N_COINS_PREMIUM_FUNDING = 18
PREMIUM_PLAUSIBLE_MAX_BPS_H = 5.0
CIBLES_CARRY_PERSISTANT = ("DASH", "INJ", "VIRTUAL", "NEO", "RUNE", "FET", "AR", "GMT", "YGG", "KAS")
ECART_PLAUSIBLE_MAX_BPS = 500.0
INTERVALLE_S_DEFAUT = 60.0


def coins_bouges_par_vaults(root: Path, *, age_max_h: float = 6.0) -> list[str]:
    try:
        data = json.loads((Path(root) / "runtime/data/coins_bouges_par_vaults.json").read_text(encoding="utf-8"))
        now_ms = time.time() * 1000
        return [str(coin).upper() for coin, ts in (data.get("coins") or {}).items() if now_ms - float(ts) <= age_max_h * 3600 * 1000]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def coins_survivants_baseline(root: Path) -> list[str]:
    try:
        data = json.loads((Path(root) / "runtime/data/cross_venue_juge_baseline.json").read_text(encoding="utf-8"))
        return [str(row.get("coin") or "").upper() for row in data.get("survivants", []) if row.get("coin")]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def coins_prioritaires(lignes: list[dict], *, n: int = N_COINS_PRIORITAIRES) -> list[str]:
    worst: dict[str, float] = {}
    for row in lignes or ():
        coin = str(row.get("coin") or "").upper(); edge = row.get("ecart_prix_bps")
        if coin and isinstance(edge, (int, float)) and abs(float(edge)) <= ECART_PLAUSIBLE_MAX_BPS:
            worst[coin] = max(worst.get(coin, 0.0), abs(float(edge)))
    return [coin for coin, _ in sorted(worst.items(), key=lambda item: -item[1])[: int(n)]]


def coins_premium_funding(lignes: list[dict], *, n: int = N_COINS_PREMIUM_FUNDING) -> list[str]:
    premiums: dict[str, float] = {}
    for row in lignes or ():
        coin = str(row.get("coin") or "").upper()
        try:
            premium = abs(float(row["hl_bps_h"]) - float(row["bin_bps_h"]))
        except (KeyError, TypeError, ValueError):
            continue
        if coin and premium <= PREMIUM_PLAUSIBLE_MAX_BPS_H:
            premiums[coin] = max(premiums.get(coin, 0.0), premium)
    return [coin for coin, _ in sorted(premiums.items(), key=lambda item: -item[1])[: int(n)]]


def _levels_hl(rep: Any, side_index: int) -> list[list[float]]:
    try:
        levels = rep["levels"][side_index]
    except (TypeError, KeyError, IndexError):
        return []
    out: list[list[float]] = []
    for item in levels[:5]:
        try:
            price, size = float(item["px"]), float(item["sz"])
        except (TypeError, ValueError, KeyError):
            continue
        if price > 0 and size > 0:
            out.append([price, size])
    return out


def _levels_binance(rep: Any, key: str) -> list[list[float]]:
    try:
        levels = rep[key]
    except (TypeError, KeyError):
        return []
    out: list[list[float]] = []
    for item in levels[:5]:
        try:
            price, size = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if price > 0 and size > 0:
            out.append([price, size])
    return out


def parser_book_hl(rep: Any) -> tuple[float, float, float, float] | None:
    bids, asks = _levels_hl(rep, 0), _levels_hl(rep, 1)
    if not bids or not asks:
        return None
    bid, bsz = bids[0]; ask, asz = asks[0]
    return (bid, ask, bsz, asz) if ask >= bid else None


def parser_depth_binance(rep: Any) -> tuple[float, float, float, float] | None:
    bids, asks = _levels_binance(rep, "bids"), _levels_binance(rep, "asks")
    if not bids or not asks:
        return None
    bid, bsz = bids[0]; ask, asz = asks[0]
    return (bid, ask, bsz, asz) if ask >= bid else None


def demi_spread_bps(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2.0
    return round((ask - bid) / 2.0 / mid * 1e4, 4) if mid > 0 else 0.0


def _minimum_four_side_capacity(hl_bids, hl_asks, bin_bids, bin_asks) -> float | None:
    books = (hl_bids, hl_asks, bin_bids, bin_asks)
    if not all(books):
        return None
    capacities = [sum(float(price) * float(size) for price, size in levels) for levels in books]
    return min(capacities) if len(capacities) == 4 else None


def ligne_carnet(coin: str, hl: tuple, binance: tuple, *, binance_symbol: str | None = None, hl_bids5=None, hl_asks5=None, bin_bids5=None, bin_asks5=None, hl_received_at_ms: float | None = None, bin_received_at_ms: float | None = None) -> dict:
    hb, ha, hbz, haz = hl; bb, ba, bbz, baz = binance
    hmid, bmid = (hb + ha) / 2.0, (bb + ba) / 2.0; ref = (hmid + bmid) / 2.0 or 1.0
    buy_hl = round((bb - ha) / ref * 1e4, 4); buy_bin = round((hb - ba) / ref * 1e4, 4)
    mapping = mapping_record(coin, binance_symbol)
    hl_bids5 = hl_bids5 or [[hb, hbz]]; hl_asks5 = hl_asks5 or [[ha, haz]]
    bin_bids5 = bin_bids5 or [[bb, bbz]]; bin_asks5 = bin_asks5 or [[ba, baz]]
    raw_capacity = _minimum_four_side_capacity(hl_bids5, hl_asks5, bin_bids5, bin_asks5)
    skew = abs(float(bin_received_at_ms) - float(hl_received_at_ms)) if hl_received_at_ms is not None and bin_received_at_ms is not None else None
    snapshot_ts_ms = max(float(hl_received_at_ms), float(bin_received_at_ms)) if skew is not None else None
    certified = bool(mapping["exact"] is True and skew is not None and skew <= MAX_VENUE_SKEW_MS and raw_capacity is not None)
    identity = "|".join((str(coin).upper(), str(binance_symbol or ""), f"{float(hl_received_at_ms):.6f}" if hl_received_at_ms is not None else "", f"{float(bin_received_at_ms):.6f}" if bin_received_at_ms is not None else "", f"{hb:.12g}", f"{bb:.12g}"))
    return {
        "coin": str(coin).upper(), "binance_symbol": binance_symbol,
        "instrument_mapping_schema": MAPPING_SCHEMA_VERSION, "instrument_mapping_exact": mapping["exact"] is True,
        "hl_bid": hb, "hl_ask": ha, "bin_bid": bb, "bin_ask": ba,
        "hl_demi_spread_bps": demi_spread_bps(hb, ha), "bin_demi_spread_bps": demi_spread_bps(bb, ba),
        "taille_min_usd": round(raw_capacity if raw_capacity is not None else min(hbz * hmid, haz * hmid, bbz * bmid, baz * bmid), 2),
        "ecart_executable_max_bps": round(max(buy_hl, buy_bin), 4),
        "hl_bids5": hl_bids5, "hl_asks5": hl_asks5, "bin_bids5": bin_bids5, "bin_asks5": bin_asks5,
        "hl_received_at_ms": hl_received_at_ms, "bin_received_at_ms": bin_received_at_ms,
        "venue_skew_ms": round(skew, 6) if skew is not None else None, "max_venue_skew_ms": MAX_VENUE_SKEW_MS,
        "snapshot_ts_ms": snapshot_ts_ms,
        "source_mode": CERTIFIED_SOURCE_MODE if certified else "LEGACY_OR_UNCERTIFIED_BOOK",
        "atomic_snapshot_certified": certified,
        "observation_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
    }


def _post_hl(coin: str, *, timeout_s: float = 8.0) -> Any:
    body = json.dumps({"type": "l2Book", "coin": coin}).encode("utf-8")
    request = urllib.request.Request(URL_HL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _get_binance(symbol_or_coin: str, *, timeout_s: float = 8.0) -> Any:
    raw = str(symbol_or_coin or "").strip().upper()
    symbol = raw if raw.endswith("USDT") else binance_perp_symbol(raw)
    if symbol is None:
        raise ValueError("instrument Binance non mappable")
    url = f"{URL_BIN_DEPTH}?symbol={symbol}&limit=5"
    with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _fetch_with_receive_timestamp(fetch, argument: str) -> tuple[Any, float]:
    """Timestamp a venue response immediately inside its read-only worker."""

    payload = fetch(argument)
    return payload, time.time_ns() / 1_000_000.0


def une_passe(root: Path, coins: list[str], *, limiteur: CF.Limiteur | None = None, cache: CF.CacheDedup | None = None, post_hl=_post_hl, get_binance=_get_binance) -> int:
    limiteur = limiteur if limiteur is not None else CF.Limiteur(0.15); raw_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cross-venue-readonly") as pool:
        for coin in coins:
            limiteur.attente(); symbol = binance_perp_symbol(coin)
            if symbol is None:
                continue
            hl_future = pool.submit(_fetch_with_receive_timestamp, post_hl, coin)
            bin_future = pool.submit(_fetch_with_receive_timestamp, get_binance, symbol)
            try:
                hl_raw, hl_received_at_ms = hl_future.result()
                bin_raw, bin_received_at_ms = bin_future.result()
                hl = parser_book_hl(hl_raw); bn = parser_depth_binance(bin_raw)
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                continue
            if not hl or not bn:
                continue
            raw_rows.append(ligne_carnet(coin, hl, bn, binance_symbol=symbol, hl_bids5=_levels_hl(hl_raw, 0), hl_asks5=_levels_hl(hl_raw, 1), bin_bids5=_levels_binance(bin_raw, "bids"), bin_asks5=_levels_binance(bin_raw, "asks"), hl_received_at_ms=hl_received_at_ms, bin_received_at_ms=bin_received_at_ms))
    clean = CF.collecter_proprement(raw_rows, source="carnet_hl_bin", champs_cle=("observation_id",), cache=cache, champs_prix=("hl_bid", "hl_ask", "bin_bid", "bin_ask"), ecart_bps_max=ECART_PLAUSIBLE_MAX_BPS, champ_ecart="ecart_executable_max_bps")
    if clean:
        CF.append_jsonl(Path(root) / SORTIE, clean)
    return len(clean)


def _lire_dispersion_recente(root: Path, *, max_lignes: int = 5000) -> list[dict]:
    path = Path(root) / DISPERSION
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict): out.append(row)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collecteur carnet HL/Binance read-only.")
    parser.add_argument("--root", default=str(RACINE)); parser.add_argument("--n-coins", type=int, default=N_COINS_PRIORITAIRES)
    parser.add_argument("--n-premium", type=int, default=N_COINS_PREMIUM_FUNDING); parser.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT); parser.add_argument("--une-fois", action="store_true")
    args = parser.parse_args(argv); root = Path(args.root); limiter, cache = CF.Limiteur(0.15), CF.CacheDedup(); total, failures = 0, 0
    while True:
        lines = _lire_dispersion_recente(root); selected: dict[str, None] = {}
        for coin in coins_prioritaires(lines, n=args.n_coins) + coins_premium_funding(lines, n=args.n_premium) + list(CIBLES_CARRY_PERSISTANT) + coins_survivants_baseline(root) + coins_bouges_par_vaults(root):
            selected.setdefault(coin, None)
        coins = list(selected)
        if not coins:
            print("[carnet] aucun coin a suivre ce tour", flush=True)
        else:
            try:
                count = une_passe(root, coins, limiteur=limiter, cache=cache); total += count; failures = 0
                print("[carnet] %s ecrits=%d cumul=%d (%d coins)" % (time.strftime("%H:%M:%S"), count, total, len(coins)), flush=True)
            except Exception as exc:  # noqa: BLE001
                failures += 1; delay = CF.backoff_jitter(failures)
                print("[carnet] erreur (%s) - backoff %.1fs" % (str(exc)[:60], delay), flush=True); time.sleep(delay)
        if args.une_fois: return 0
        time.sleep(max(30.0, float(args.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
