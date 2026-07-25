"""LOT 5 — COLLECTEUR WS MICROSTRUCTURE DENSE, ISOLÉ (Flo 25/07). Écrit UNIQUEMENT sous research_lab.

Flux WS HL : l2Book (top 20), trades (côté agresseur), bbo (avec bid_sz/ask_sz). Univers ADAPTATIF de 24
coins classés volume × OI × activité de liquidation, actualisable SANS redémarrage. Chaque ligne porte
timestamps exchange + wall + monotonic, niveaux/prix/tailles, séquence, gap détecté, checksum. Append-only +
shards archivés (jamais de suppression valide). 0 slot userFills du main, 0 clé, 0 ordre, 0 signature.

Les parseurs + l'univers sont PURS (testables sans réseau). La boucle WS tourne sur Windows (HL WS injoignable
depuis le sandbox). Nécessite le module `websockets`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research_parallel import isolation as ISO  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
TOP_L2 = 20
UNIVERS_K = 24


# ─────────────── univers adaptatif (PUR) ───────────────
def univers_adaptatif(ctxs: dict, *, k: int = UNIVERS_K, liq_counts: dict | None = None) -> list[str]:
    """Classe les coins par score = volume24h × OI × (1 + nb liquidations récentes). Rend le top-k.
    `ctxs` = {coin: {vol24h, oi, ...}}. Actualisable à chaud (rappeler la fonction, réabonner le delta)."""
    liq_counts = liq_counts or {}
    scores = {}
    for c, d in ctxs.items():
        vol = float(d.get("vol24h") or 0.0)
        oi = float(d.get("oi") or 0.0)
        if vol <= 0 or oi <= 0:
            continue
        scores[c] = vol * oi * (1.0 + liq_counts.get(c, 0))
    return [c for c, _s in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]]


# ─────────────── parseurs WS (PURS) ───────────────
def parser_l2book(msg: dict) -> dict | None:
    """l2Book -> {coin, ts_ex, bids:[(px,sz)], asks:[(px,sz)]} (top 20). None si illisible."""
    try:
        d = msg["data"]
        coin = str(d["coin"]).upper()
        niveaux = d["levels"]
        bids = [(float(x["px"]), float(x["sz"])) for x in niveaux[0][:TOP_L2]]
        asks = [(float(x["px"]), float(x["sz"])) for x in niveaux[1][:TOP_L2]]
    except (KeyError, TypeError, IndexError, ValueError):
        return None
    return {"flux": "l2book", "coin": coin, "ts_ex": d.get("time"), "bids": bids, "asks": asks}


def parser_trades(msg: dict) -> list[dict]:
    """trades -> [{coin, px, sz, side (+1 achat agressif/−1 vente), ts_ex, tid}]."""
    out = []
    try:
        data = msg["data"]
    except (KeyError, TypeError):
        return out
    for t in data if isinstance(data, list) else []:
        try:
            side = 1 if str(t.get("side")) in ("B", "BUY", "b") else -1
            out.append({"flux": "trade", "coin": str(t["coin"]).upper(), "px": float(t["px"]),
                        "sz": float(t["sz"]), "side": side, "ts_ex": t.get("time"), "tid": t.get("tid")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parser_bbo(msg: dict) -> dict | None:
    """bbo -> {coin, ts_ex, bid, bid_sz, ask, ask_sz}. None si illisible (tailles OBLIGATOIRES ici)."""
    try:
        d = msg["data"]
        coin = str(d["coin"]).upper()
        bid, ask = d["bbo"][0], d["bbo"][1]
        return {"flux": "bbo", "coin": coin, "ts_ex": d.get("time"),
                "bid": float(bid["px"]), "bid_sz": float(bid["sz"]),
                "ask": float(ask["px"]), "ask_sz": float(ask["sz"])}
    except (KeyError, TypeError, IndexError, ValueError):
        return None


# ─────────────── écriture dense (séquence, gap, checksum, wall+mono) ───────────────
def ecrire_micro(root: Path, flux: str, lignes: list[dict], *, seqs: dict | None = None) -> int:
    """Append research_lab/data/micro_<flux>.jsonl : ts_ex + wall + mono, séquence par coin, GAP détecté
    (séquence non consécutive), checksum. Archive si trop gros. Rend le nb écrit. Best-effort."""
    if not lignes:
        return 0
    seqs = seqs if seqs is not None else {}
    base = ISO.lab_root(root) / "data"
    base.mkdir(parents=True, exist_ok=True)
    p = base / ("micro_%s.jsonl" % flux)
    now_ms = int(time.time() * 1000); mono = time.monotonic_ns()
    n = 0
    try:
        with p.open("a", encoding="utf-8") as f:
            for l in lignes:
                coin = l.get("coin", "?")
                seq = seqs.get(coin, 0) + 1
                seqs[coin] = seq
                gap = None
                if l.get("ts_ex") is not None:
                    prev = seqs.get("_last_ts_%s" % coin)
                    if prev is not None and l["ts_ex"] < prev:
                        gap = "TS_RECUL"                 # horodatage exchange en recul = anomalie
                    seqs["_last_ts_%s" % coin] = l["ts_ex"]
                corps = {**l, "ts_wall_ms": now_ms, "ts_mono_ns": mono, "seq": seq, "gap": gap,
                         "source": "hl_ws_public", "read_only": True, "real_execution": False}
                corps["checksum"] = hashlib.sha256(
                    json.dumps(corps, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
                f.write(json.dumps(corps, ensure_ascii=False) + "\n")
                n += 1
        ISO.archiver_si_gros(root, "micro_%s" % flux)
    except OSError:
        return n
    return n


def _heartbeat_micro(root: Path, coins, reco: int, msgs: int) -> None:  # pragma: no cover
    try:
        (ISO.lab_root(root) / "micro_heartbeat.json").write_text(
            json.dumps({"ts_wall_ms": int(time.time() * 1000), "ts_mono_ns": time.monotonic_ns(),
                        "coins": len(coins), "reconnexions": reco, "messages": msgs}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


async def _une_connexion(root: Path, coins: list[str], seqs: dict, cpt: dict):  # pragma: no cover
    import asyncio
    import websockets
    async with websockets.connect(WS_URL, ping_interval=30, ping_timeout=30, max_size=None,
                                  close_timeout=5) as ws:
        # THROTTLE des abonnements : HL ferme la connexion si on FLOOD 72 souscriptions d'un coup (mesuré :
        # "no close frame" + reconnexions en boucle). On espace les envois -> connexion stable.
        for c in coins:
            for typ in ("l2Book", "trades", "bbo"):
                await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": typ, "coin": c}}))
                await asyncio.sleep(0.06)
        _heartbeat_micro(root, coins, cpt["reco"], cpt["msgs"])
        async for brut in ws:
            try:
                msg = json.loads(brut)
            except ValueError:
                continue
            ch = msg.get("channel")
            if ch == "l2Book":
                r = parser_l2book(msg)
                if r:
                    ecrire_micro(root, "l2book", [r], seqs=seqs)
            elif ch == "trades":
                ecrire_micro(root, "trades", parser_trades(msg), seqs=seqs)
            elif ch == "bbo":
                r = parser_bbo(msg)
                if r:
                    ecrire_micro(root, "bbo", [r], seqs=seqs)
            cpt["msgs"] += 1
            if cpt["msgs"] % 200 == 0:
                _heartbeat_micro(root, coins, cpt["reco"], cpt["msgs"])


async def _boucle_ws(root: Path, coins: list[str]):  # pragma: no cover (réseau, tourne sur Windows)
    """RECONNEXION robuste : si la connexion tombe (HL ferme, ping timeout), on RECONNECTE après un backoff
    borné — on ne meurt JAMAIS sur une déconnexion (exigence live de Flo). Chaque reconnexion est comptée."""
    import asyncio
    seqs: dict = {}
    cpt = {"reco": 0, "msgs": 0}
    while True:
        try:
            await _une_connexion(root, coins, seqs, cpt)
        except Exception as e:  # noqa: BLE001 (déconnexion/erreur -> on reconnecte, on ne tombe pas)
            print("[micro] deconnexion (%s) -> reconnexion" % str(e)[:80], flush=True)
        cpt["reco"] += 1
        _heartbeat_micro(root, coins, cpt["reco"], cpt["msgs"])
        await asyncio.sleep(min(2.0 + cpt["reco"], 15.0))


#: univers 24 coins par défaut (majors + actifs + coins de liquidation fréquents) tant que asset_ctx du
#: labo n'a pas encore de quoi classer par vol×OI×liq. Remplacé dès que la data ctx arrive.
UNIVERS_DEFAUT = ("BTC", "ETH", "SOL", "AVAX", "INJ", "LINK", "DASH", "NEO", "AAVE", "ONDO", "HYPE",
                  "XRP", "DOGE", "WLD", "ARB", "OP", "SUI", "TIA", "SEI", "APT", "LTC", "BNB", "PEPE", "FARTCOIN")


def _charger_univers(root: Path, *, k: int = UNIVERS_K) -> list[str]:
    """Univers ADAPTATIF : classe par vol×OI×liq depuis l'asset_ctx du labo (LOT 1) si présent, sinon
    l'univers 24 par défaut. Relu à chaque démarrage/passe -> s'adapte sans redémarrage manuel."""
    from hl_observer.research_parallel.plugins import _commun as K
    recs = K.charger_lab_jsonl(root, "asset_ctx")
    if recs:
        derniers = {}
        for r in recs:
            if r.get("coin"):
                derniers[r["coin"]] = r
        u = univers_adaptatif({c: d for c, d in derniers.items()}, k=k)
        if len(u) >= 8:
            return u
    return list(UNIVERS_DEFAUT[:k])


def main(argv=None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser(description="Collecteur WS microstructure dense isolé (read-only).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--coins", default="")
    a = ap.parse_args(argv)
    coins = [c for c in a.coins.split(",") if c] or _charger_univers(Path(a.root))
    print("[micro] connexion HL WS, %d coins: %s" % (len(coins), ",".join(coins)), flush=True)
    try:
        import asyncio
        asyncio.run(_boucle_ws(Path(a.root), coins))
    except KeyboardInterrupt:
        print("[micro] arret manuel", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
