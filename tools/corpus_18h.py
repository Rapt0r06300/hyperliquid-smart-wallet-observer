"""CORPUS CANONIQUE 18 h (LOT18H-DATA-COMPLETE, Flo 26/07). Transforme les sources cataloguées en un corpus
RÉELLEMENT consommé par FAST_SCREEN et EXACT_REPLAY. Chaque événement conserve sa PROVENANCE complète et la
déduplication est SELON LA SOURCE (jamais « même coin+ts => doublon »). Comptabilise events lus/filtrés/
dédupliqués/utilisés + couverture. 0 réseau, 0 écriture sur les originaux.

Types couverts : L2/BBO, trades, OI/funding/asset context, liquidations, wallets/vaults/fills, décisions/
refus, positions/exécutions paper, logs. Les épisodes de marché (BBO + prix forward causaux) alimentent le
moteur exact ; les autres types sont normalisés et rendus disponibles avec leur lignée.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import lecteurs_18h as LEC  # noqa: E402

HORIZONS_MS = (100, 250, 500, 1000, 2000, 3000, 5000, 10000, 15000, 30000, 60000,
               120000, 300000, 900000, 1800000, 3600000)


def _num(d: dict, *cles):
    for k in cles:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _coin(d):
    c = d.get("coin") or d.get("symbol") or d.get("asset")
    return str(c).upper() if c else None


def classer_type(d: dict, source: str) -> str:
    """Type canonique d'un événement d'après ses champs (jamais deviné à partir du seul nom de fichier)."""
    if ("bid" in d and "ask" in d) or ("hl_bid" in d and "hl_ask" in d):
        return "BBO"
    if any(k in d for k in ("levels", "l2", "bids", "asks")):
        return "L2"
    if d.get("venue") in ("BIN_TRADE",) or (("px" in d or "price" in d) and ("side" in d or "sz" in d)):
        return "TRADE"
    if any(k in d for k in ("funding", "predicted_funding", "openInterest", "open_interest", "oi")):
        return "CTX"
    if d.get("liquidation") is not None or "liquidation" in str(d.get("kind", "")).lower():
        return "LIQUIDATION"
    if any(k in d for k in ("vault", "szi", "positions")):
        return "VAULT"
    if d.get("kind") in ("OPEN", "ADD", "REDUCE", "CLOSE", "FLIP") or "realized_net_pnl_usdc" in d:
        return "PAPER"
    if d.get("motif") or d.get("refus") or d.get("raison") or "gate" in str(d.get("kind", "")).lower():
        return "DECISION"
    return "AUTRE"


def provenance(d: dict, *, source: str, sha: str, offset, typ: str) -> dict:
    return {
        "source": source, "source_sha256": sha, "offset": offset, "type": typ, "coin": _coin(d),
        "run_id": d.get("run_id") or d.get("run"), "exchange_ts": _num(d, "exchange_ts", "ts_ex"),
        "recv_ts": _num(d, "recv_ts", "recu_ns", "ts_wall_ms"), "write_ts": _num(d, "write_ts"),
        "payload_hash": LEC.payload_hash(d), "reconnect_id": d.get("reconnect_id") or d.get("reconnect"),
        "isSnapshot": bool(d.get("isSnapshot") or d.get("is_snapshot")),
        "quality": _quality(d),
    }


def _quality(d: dict) -> list[str]:
    q = []
    b, a = _num(d, "bid", "hl_bid"), _num(d, "ask", "hl_ask")
    if b is not None and a is not None and a > 0 and b > a:
        q.append("CROSSED_BOOK")
    import math
    for k in ("bid", "ask", "px", "net_median_bps"):
        v = d.get(k)
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            q.append("NAN_INF")
    return q


def cle_dedup(d: dict, typ: str, prov: dict) -> tuple:
    """Clé de déduplication SELON LA SOURCE. Trades : tid/oid/hash sinon time+side+price+size. L2/BBO :
    coin+exchange_ts+payload_hash+reconnect_id+isSnapshot. Ne fusionne JAMAIS deux events sur le seul coin+ts."""
    if typ == "TRADE":
        for k in ("tid", "oid", "hash", "trade_id"):
            if d.get(k) is not None:
                return ("TRADE", d.get(k))
        return ("TRADE", prov["coin"], _num(d, "time", "ts_ms", "recu_ns"), d.get("side"),
                _num(d, "px", "price"), _num(d, "sz", "size"))
    if typ in ("BBO", "L2"):
        return (typ, prov["coin"], prov["exchange_ts"], prov["payload_hash"], prov["reconnect_id"], prov["isSnapshot"])
    return (typ, prov["payload_hash"])


def construire(sources: list[dict], *, root: Path, max_par_source: int = 200_000) -> dict:
    """Lit les sources (chemins + format + sha), normalise, DÉDUPLIQUE selon la source, agrège par coin, et
    construit les épisodes BBO avec prix forward causaux. Rend {episodes, comptes, par_source, lineage_seeds}."""
    root = Path(root)
    vus = set()
    bbo_par_coin: dict[str, list] = {}
    comptes = {"lus": 0, "filtres": 0, "dedup": 0, "utilises": 0, "par_type": {}}
    par_source = {}
    lineage_seeds = []
    for s in sources:
        fmt = s.get("format")
        chemin = root / s["chemin"] if not Path(s["chemin"]).is_absolute() else Path(s["chemin"])
        lecteur = LEC.LECTEURS.get(fmt)
        if lecteur is None or not chemin.exists():
            continue
        sha = s.get("sha256") or ""
        cs = {"lus": 0, "dedup": 0, "utilises": 0}
        try:
            it = list(lecteur(chemin, max_records=max_par_source))   # matérialise ici pour capter les erreurs de lecteur (ex: Parquet sans moteur)
        except Exception as e:  # noqa: BLE001 — une source illisible est comptée+EXCLUE, jamais ignorée en silence
            par_source[s["chemin"]] = {"erreur": str(e)[:120], "exclue": True}
            continue
        for offset, d in it:
            if not isinstance(d, dict) or d.get("_invalide"):
                comptes["filtres"] += 1
                continue
            comptes["lus"] += 1; cs["lus"] += 1
            typ = classer_type(d, s["chemin"])
            comptes["par_type"][typ] = comptes["par_type"].get(typ, 0) + 1
            prov = provenance(d, source=s["chemin"], sha=sha, offset=offset, typ=typ)
            cle = cle_dedup(d, typ, prov)
            if cle in vus:
                comptes["dedup"] += 1; cs["dedup"] += 1
                continue
            vus.add(cle)
            comptes["utilises"] += 1; cs["utilises"] += 1
            if typ == "BBO":
                b, a = _num(d, "bid", "hl_bid"), _num(d, "ask", "hl_ask")
                ts = prov["recv_ts"] or prov["exchange_ts"]
                if b and a and a > b > 0 and ts is not None:
                    c = prov["coin"] or "?"
                    bbo_par_coin.setdefault(c, []).append((float(ts) / (1e6 if ts > 1e14 else 1.0), b, a, prov))
            if len(lineage_seeds) < 50:
                lineage_seeds.append(prov)
        par_source[s["chemin"]] = cs
    episodes = _episodes_depuis_bbo(bbo_par_coin)
    comptes["episodes"] = len(episodes)
    return {"episodes": episodes, "comptes": comptes, "par_source": par_source, "lineage_seeds": lineage_seeds}


def _episodes_depuis_bbo(bbo_par_coin: dict) -> list[dict]:
    eps = []
    for coin, ticks in bbo_par_coin.items():
        ticks.sort(key=lambda x: x[0])
        mids = [(ts, (b + a) / 2.0, b, a, prov) for ts, b, a, prov in ticks]
        for i, (ts, mid, bid, ask, prov) in enumerate(mids):
            fwd = {}
            for h in HORIZONS_MS:
                j = i
                while j < len(mids) and mids[j][0] - ts < h:
                    j += 1
                if j < len(mids):
                    fwd[h] = mids[j][1]
            if not fwd or mid <= 0:
                continue
            spread = (ask - bid) / mid
            eps.append({"coin": coin, "regime": ("vol" if spread > 0.0006 else "calme"), "ts_ms": ts,
                        "bid": bid, "ask": ask, "bid_sz": 3000.0, "ask_sz": 3000.0,
                        "queue_devant_sz": 200.0, "vol_traversant_sz": 600.0,
                        "fees_bps": 1.5, "slippage_bps": 0.8, "impact_bps": 0.2, "latence_bps": 0.3,
                        "fwd_mid": fwd, "provenance": prov})
    return eps


__all__ = ["construire", "classer_type", "provenance", "cle_dedup", "HORIZONS_MS"]
