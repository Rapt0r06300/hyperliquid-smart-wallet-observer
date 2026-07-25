"""HISTORICAL_HOLDOUT_V1 — parseur node_fills + L2 + backtest GELÉ (rectif Flo 25/07).

PUR : aucun réseau, aucune position, aucun ordre. Applique EXACTEMENT la variante pré-enregistrée
(CONTINUATION/LATE + OFI top-5, **taker**, **9 bps A/R**, même horizon, mêmes gates) en RÉUTILISANT
`metaorder_shadow` (métaordres, stades, forward net, placebo, coûts L2, IC clusterisé, capacité) — donc
les MÊMES règles que le live, pas une 2ᵉ implémentation.

Chaîne : (1) décompresser lz4 → (2) parser node_fills et **filtrer sur les vaults suivis** (attribution) →
(3) parser L2 → tapes de mid + carnets horodatés → (4) `construire_signaux` par (vault,coin) → (5) surcharger
le coût par le **carnet L2 réel au fill** (postérieur) + calculer l'**OFI top-5** (snapshots successifs) →
(6) population gelée + rapport (couverture/trous, coûts exécutables, placebo, IC clusterisé, capacité).

Règle dure — AUCUNE approximation : un fill sans attribution vault, ou un slice sans carnet L2 synchronisé,
est **EXCLU**, jamais reconstruit ni deviné. Une couverture trouée est annoncée trouée.
"""
from __future__ import annotations

import json
from bisect import bisect_right
from typing import Iterable

from hl_observer.experimental import metaorder_shadow as MS

FEE_AR_BPS = MS.FEE_AR_BASE_BPS               # 9 bps A/R (variante gelée)
HORIZON_MS = MS.HORIZON_FWD_MS
COPY_NOTIONAL_USD = MS.COPY_NOTIONAL_USD
STADES_CIBLES = ("CONTINUATION", "LATE_STAGE")


# ============================ décompression (lz4) =================================================
def decompresser_lz4(octets: bytes) -> bytes:
    """Décompresse un objet .lz4 de l'archive HL. Frame d'abord (format de la CLI officielle), bloc en secours."""
    import lz4.block
    import lz4.frame
    try:
        return lz4.frame.decompress(octets)
    except Exception:                                            # noqa: BLE001
        return lz4.block.decompress(octets, uncompressed_size=max(len(octets) * 32, 1 << 20))


def _lignes_json(donnee) -> Iterable[dict]:
    txt = donnee.decode("utf-8", "replace") if isinstance(donnee, (bytes, bytearray)) else donnee
    for l in txt.splitlines():
        l = l.strip()
        if not l:
            continue
        try:
            yield json.loads(l)
        except (ValueError, TypeError):
            continue


# ============================ node_fills → attribution vault =======================================
def iter_fills_bruts(rec) -> Iterable[tuple[str, dict]]:
    """(user_minuscule, fill) depuis un enregistrement node_fills, TOLÉRANT à plusieurs formes documentées :
    userFills à plat ({user, coin, px...}), par bloc ({fills|events:[{user, fill|...}]}), ou paires [user, fill]."""
    if isinstance(rec, dict) and "user" in rec and ("px" in rec or "coin" in rec):
        yield str(rec["user"]).lower(), rec
        return
    if isinstance(rec, dict):
        lot = rec.get("fills") or rec.get("events")
        if isinstance(lot, list):
            for e in lot:
                if isinstance(e, dict) and "user" in e:
                    f = e.get("fill") if isinstance(e.get("fill"), dict) else e
                    yield str(e["user"]).lower(), f
                elif isinstance(e, (list, tuple)) and len(e) == 2 and isinstance(e[1], dict):
                    yield str(e[0]).lower(), e[1]
            return
    if isinstance(rec, (list, tuple)):
        for e in rec:
            if isinstance(e, (list, tuple)) and len(e) == 2 and isinstance(e[1], dict):
                yield str(e[0]).lower(), e[1]


def charger_fills(records: Iterable, vaults: Iterable[str]) -> dict:
    """{(vault, coin): [fills triés+dédupliqués]} — UNIQUEMENT pour les vaults suivis (attribution stricte)."""
    vs = {str(v).lower() for v in vaults}
    par_vc: dict = {}
    for rec in records:
        for user, f in iter_fills_bruts(rec):
            if user not in vs:
                continue
            coin = str(f.get("coin") or "").upper()
            if not coin or f.get("px") is None or f.get("sz") is None:
                continue
            par_vc.setdefault((user, coin), []).append(f)
    for k, lst in par_vc.items():
        par_vc[k] = sorted(MS.dedup_fills(lst), key=lambda x: int(x.get("time") or 0))
    return par_vc


# ============================ L2 → tapes de mid + carnets horodatés ================================
def charger_l2(records: Iterable) -> dict:
    """{coin: ([temps triés], [carnets alignés])}. Carnet = {'levels':[bids,asks]} niveaux {px,sz}."""
    brut: dict = {}
    for rec in records:
        d = rec.get("data") if isinstance(rec, dict) and isinstance(rec.get("data"), dict) else rec
        if not isinstance(d, dict):
            continue
        coin = str(d.get("coin") or "").upper()
        t = int(d.get("time") or d.get("t") or 0)
        levels = d.get("levels")
        if not coin or not levels or not t:
            continue
        brut.setdefault(coin, []).append((t, {"levels": levels}))
    out: dict = {}
    for coin, paires in brut.items():
        paires.sort(key=lambda x: x[0])
        out[coin] = ([t for t, _ in paires], [b for _, b in paires])
    return out


def _mid(book: dict):
    try:
        return 0.5 * (float(book["levels"][0][0]["px"]) + float(book["levels"][1][0]["px"]))
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def tape_mids(l2_coin) -> list:
    if not l2_coin:
        return []
    temps, books = l2_coin
    out = []
    for t, b in zip(temps, books):
        m = _mid(b)
        if m is not None:
            out.append((t, m))
    return out


def carnet_avant(l2_coin, ts: int):
    """Dernier carnet à un temps ≤ ts (état PRÉ)."""
    if not l2_coin:
        return None
    temps, books = l2_coin
    i = bisect_right(temps, ts) - 1
    return books[i] if i >= 0 else None


def carnet_apres(l2_coin, ts: int):
    """Premier carnet à un temps ≥ ts (état d'ENTRÉE, postérieur au fill = L2 synchronisé)."""
    if not l2_coin:
        return None
    temps, books = l2_coin
    i = bisect_right(temps, ts - 1)
    return books[i] if i < len(temps) else None


def ofi_du_fill(l2_coin, ts: int):
    """OFI top-5 entre le carnet PRÉ (≤ ts-1) et le carnet d'entrée (≥ ts). None si un état manque."""
    pre, post = carnet_avant(l2_coin, ts - 1), carnet_apres(l2_coin, ts)
    if pre is None or post is None:
        return None
    return MS.ofi_top5(pre, post)


# ============================ signaux + coût L2 réel + OFI ==========================================
def signaux_holdout(par_vc: dict, l2: dict, *, coin_placebo: str = "BTC") -> list:
    """Un signal par slice (via `construire_signaux`), avec coût SURCHARGÉ par le carnet L2 réel au fill
    (postérieur = synchronisé) et l'OFI top-5. `l2_sync=False` ou `ofi_mesurable=False` → exclu de la population."""
    tape_btc = tape_mids(l2.get(coin_placebo))
    out: list = []
    for (vault, coin), fills in par_vc.items():
        l2_coin = l2.get(coin)
        tape_coin = tape_mids(l2_coin)
        sigs = MS.construire_signaux(fills, vault=vault, idx_twap={}, tape_coin=tape_coin,
                                     tape_btc=tape_btc, cout_fn=None, horizon_ms=HORIZON_MS,
                                     copy_notional_usd=COPY_NOTIONAL_USD)
        for s in sigs:
            t = int(s.get("fill_time") or 0)
            book = carnet_apres(l2_coin, t)                       # entrée POSTÉRIEURE au fill
            if book is None:
                s["l2_sync"], s["ofi_top5"], s["ofi_mesurable"], s["_book"] = False, None, False, None
                out.append(s)
                continue
            s["l2_sync"], s["_book"] = True, book
            comp = MS.cout_composants(book, COPY_NOTIONAL_USD, s["sens"], FEE_AR_BPS)
            if comp and s.get("pnl_net_bps") is not None:
                brut = s["pnl_net_bps"] + (s.get("cout_ar_bps") or 0.0)   # regross (le coût screening est retiré)
                s["cout_ar_bps"], s["cout_source"] = comp["cout_ar_bps"], "l2_historique"
                s["spread_bps"], s["slippage_bps"] = comp["spread_bps"], comp["slippage_vwap_bps"]
                s["pnl_net_bps"] = round(brut - comp["cout_ar_bps"], 3)
            of = ofi_du_fill(l2_coin, t)
            s["ofi_top5"], s["ofi_mesurable"] = of, (of is not None)
            out.append(s)
    return out


def population_gelee(sigs: list) -> list:
    """Variante GELÉE : stade CONTINUATION/LATE, taker, L2 synchronisé, OFI mesurable, PnL net défini."""
    return [s for s in sigs if s.get("stade") in STADES_CIBLES and s.get("maker_taker") == "taker"
            and s.get("l2_sync") and s.get("ofi_mesurable") and s.get("pnl_net_bps") is not None]


def couverture(sigs: list) -> dict:
    cibles = [s for s in sigs if s.get("stade") in STADES_CIBLES and s.get("maker_taker") == "taker"]
    sync = [s for s in cibles if s.get("l2_sync")]
    ofiok = [s for s in sync if s.get("ofi_mesurable")]
    return {"slices_total": len(sigs), "cibles_taker": len(cibles), "l2_synchronise": len(sync),
            "ofi_mesurable": len(ofiok),
            "pct_l2_sync": round(100 * len(sync) / max(len(cibles), 1), 1),
            "n_metaordres_population": len({s.get("metaorder_id") for s in population_gelee(sigs)})}


def _capacite(pop: list) -> dict:
    caps = {}
    for notional in MS.NOTIONALS_DEFAUT:
        paires = []
        for s in pop:
            b, alpha = s.get("_book"), s.get("alpha_vs_marche_bps")
            if not b or alpha is None:
                continue
            comp = MS.cout_composants(b, notional, s["sens"], FEE_AR_BPS)
            if comp:
                paires.append((s.get("metaorder_id"), alpha - comp["cout_ar_bps"]))
        caps[str(int(notional))] = MS.bootstrap_clusterise(paires)
    prouvee = 0.0
    for notional in MS.NOTIONALS_DEFAUT:
        ic = caps[str(int(notional))]["ic_bas"]
        if ic is not None and ic > 0:
            prouvee = notional
    return {"par_palier": caps, "capacite_prouvee_usd": prouvee}


def rapport(sigs: list) -> dict:
    """Rapport holdout : couverture, PnL net (IC clusterisé par métaordre), placebo, capacité, verdict.
    AUCUNE promotion si l'IC bas clusterisé n'est pas strictement > 0."""
    pop = population_gelee(sigs)
    ic = MS.bootstrap_clusterise([(s["metaorder_id"], s["pnl_net_bps"]) for s in pop])
    placebo = MS.bootstrap_clusterise([(s["metaorder_id"], s.get("alpha_vs_marche_bps")) for s in pop
                                       if s.get("alpha_vs_marche_bps") is not None])
    capa = _capacite(pop)
    ic_bas = ic.get("ic_bas")
    promu = bool(ic_bas is not None and ic_bas > 0 and capa["capacite_prouvee_usd"] > 0)
    return {
        "couverture": couverture(sigs),
        "n_metaordres": ic.get("n_clusters"), "n_slices_population": ic.get("n_obs"),
        "pnl_net_bps_ic": ic, "placebo_alpha_marche_ic": placebo,
        "pnl_net_usd_moy": (round(ic["moy"] / 10000.0 * COPY_NOTIONAL_USD, 4) if ic.get("moy") is not None else None),
        "roi_net_pct": (round(ic["moy"] / 100.0, 4) if ic.get("moy") is not None else None),
        "par_stade": MS.stats_par_stade(pop), "capacite": capa,
        "verdict": "PROMOTION_POSSIBLE" if promu else "PAS_DE_PROMOTION_IC_BAS_NON_POSITIF",
        "regle": "PRELIMINAIRE — aucune promotion si l'IC bas clusterise (OOS) n'est pas > 0.",
    }


def executer(node_fills_records: Iterable, l2_records: Iterable, vaults: Iterable[str],
             *, coin_placebo: str = "BTC") -> dict:
    """Bout-en-bout (données DÉJÀ décompressées → itérables de dicts). Rend le rapport holdout."""
    par_vc = charger_fills(node_fills_records, vaults)
    l2 = charger_l2(l2_records)
    sigs = signaux_holdout(par_vc, l2, coin_placebo=coin_placebo)
    r = rapport(sigs)
    r["vaults_avec_fills"] = sorted({v for (v, _c) in par_vc})
    r["coins_l2"] = sorted(l2)
    return r


__all__ = ["decompresser_lz4", "iter_fills_bruts", "charger_fills", "charger_l2", "tape_mids",
           "carnet_avant", "carnet_apres", "ofi_du_fill", "signaux_holdout", "population_gelee",
           "couverture", "rapport", "executer", "FEE_AR_BPS", "HORIZON_MS", "COPY_NOTIONAL_USD"]
