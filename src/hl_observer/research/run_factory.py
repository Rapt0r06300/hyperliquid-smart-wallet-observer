"""ALPHA FACTORY — PIPELINE exécutable (FIX-01) : pilote par le REGISTRE DES FAMILLES, chaque famille a un
ADAPTATEUR qui EXÉCUTE réellement son expérience → un trial mesuré, ou un `BLOCKED_EXTERNAL` PRÉCIS.

Fini le registre déclaratif : `run_all` parcourt `factory_families.FAMILLES` et, pour CHAQUE famille
ACTIVE/SHADOW/BLOCKED, appelle son adaptateur. L'adaptateur charge la donnée présente et lance la vraie
expérience (OFI, population, lead-lag, MLOFI, anticipation, cross-venue, TWAP…) ; si la donnée manque, il
renvoie un BLOCKED avec la raison exacte. Chaque famille produit donc UNE ligne canonique. Robuste (une
exception = ligne ERROR, pas de crash). Registre append-only + dédup (FIX-03).

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import collections
import json
import os
from typing import Any

from hl_observer.research import alpha_factory as F
from hl_observer.research import factory_families as _fam
from hl_observer.research import mlofi as _ml
from hl_observer.research import ofi_microprice as _ofi
from hl_observer.research import wallet_binance_anticipation as _wba
from hl_observer.research import wallet_population as _wp

U = F.UNMEASURABLE


def _existe(path: str) -> bool:
    return bool(path) and os.path.exists(path)


def _blocked(famille: str, raison: str) -> dict[str, Any]:
    return F.ligne_canonique("[%s]" % famille, config_frozen="—", verdict="BLOCKED_EXTERNAL",
                             data="absente", notes=raison)


# ── Adaptateurs : chacun EXÉCUTE ou renvoie BLOCKED précis ─────────────────────────────
def _adapt_ofi(data_dir: str, fee_bps: float) -> dict[str, Any]:
    best_row = None
    for coin in ("BTC", "ETH", "SOL", "HYPE"):
        path = os.path.join(data_dir, "_ofi_%s.csv" % coin)
        if not _existe(path):
            continue
        d = _ofi.charger_book_csv(path)
        serie = d.get(coin, [])
        if len(serie) < 500:
            continue
        r = _ofi.experience_complete(serie, coin=coin, horizon_pas=2, fee_bps=fee_bps)
        best = max((v for v in r["par_feature"].values() if isinstance(v.get("net_bps_oos"), (int, float))),
                   key=lambda v: v["net_bps_oos"], default=None)
        if best is None:
            continue
        row = F.ligne_canonique("OFI/microstructure %s" % coin, config_frozen="l2_book; DISC->FREEZE->OOS; h=2",
                                data="l2_book %s" % coin, event="imbalance/OFI/micro", execution="TAKER/TAKER",
                                n_independent=best.get("n_votes_independants"), gross_bps=best.get("gross_bps_oos"),
                                fees_bps=fee_bps, net_bps=best.get("net_bps_oos"), lcb_net_bps=best.get("lcb_net_bps"),
                                verdict=best.get("verdict", "MORE_DATA"))
        if best_row is None or (isinstance(row["net_bps"], (int, float))
                                and isinstance(best_row["net_bps"], (int, float)) and row["net_bps"] > best_row["net_bps"]):
            best_row = row
    return best_row or _blocked("ofi_microstructure", "aucun _ofi_<coin>.csv exploitable dans data_dir")


def _adapt_population(data_dir: str, fee_bps: float) -> dict[str, Any]:
    path = os.path.join(data_dir, "leader_fills_forward.jsonl")
    if not _existe(path):
        return _blocked("copy_population", "leader_fills_forward.jsonl absent")
    out = _wp.classer_population(path, cout_bps=fee_bps, min_fills=8)
    classement = out["classement"]
    # FIX-34 : distribution des edges nets par wallet INDÉPENDANT (hors entités co-tradant) → pf/es réels du trial.
    indep = [l for l in classement if not l.get("entite_potentiellement_liee")]
    cand = [l for l in indep if l.get("verdict") in ("CANDIDAT", "FORWARD_REQUIS")]
    edges = [l["net_bps_mean"] for l in indep if isinstance(l.get("net_bps_mean"), (int, float))]
    gross = [l["gross_bps"] for l in indep if isinstance(l.get("gross_bps"), (int, float))]
    m = F.metriques_distribution(edges)
    gross_moy = round(sum(gross) / len(gross), 4) if gross else U
    net_moy = round(sum(edges) / len(edges), 4) if edges else U
    # « Copy population » n'est un CANDIDAT que si l'edge net moyen INDÉPENDANT est > 0 ET qu'un wallet passe son
    # propre gate : verdict et net_bps ne peuvent plus se contredire (jamais CANDIDAT avec net négatif).
    edge_positif = isinstance(net_moy, (int, float)) and net_moy > 0
    verdict = "CANDIDAT" if (cand and edge_positif) else "KILL"
    return F.ligne_canonique("Copy population (%d wallets)" % out["n_evalues"],
                             config_frozen="grappes wallet:coin:jour; net copyable edge", data="leader_fills_forward",
                             event="wallet fills", execution="TAKER/TAKER", n_raw=out["n_lignes_streamees"],
                             n_independent=(len(edges) or U), gross_bps=gross_moy, fees_bps=fee_bps, net_bps=net_moy,
                             pf=m["pf"], es=m["es"], verdict=verdict,
                             notes="%d candidats indep ; %d clusters entite ; pf/es/net sur %d wallets independants"
                                   % (len(cand), out["n_clusters_entite"], len(edges)))


def _adapt_mlofi(data_dir: str, fee_bps: float) -> dict[str, Any]:
    path = os.path.join(data_dir, "metaorder_l2_tape.jsonl")
    if not _existe(path):
        return _blocked("mlofi", "metaorder_l2_tape.jsonl (top5) absent")
    bycoin: dict[str, list] = collections.defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                x = json.loads(line)
            except Exception:
                continue
            t = x.get("top5")
            if t and t.get("bids") and t.get("asks") and x.get("coin") and x.get("fill_time"):
                bycoin[x["coin"]].append((x["fill_time"], t))
    for coin, seq in bycoin.items():
        seq.sort(key=lambda z: z[0])
        books = [t for _, t in seq]
        if len(books) >= 60:
            r = _ml.experience_mlofi(books, niveaux=5, horizon_pas=1, fee_bps=fee_bps)
            return F.ligne_canonique("MLOFI multi-niveaux (%s)" % coin, config_frozen="top5; L1/L3/L5; h=1",
                                     data="metaorder top5", event="MLOFI", execution="TAKER/TAKER",
                                     n_independent=r.get("n_oos_MLOFI"), net_bps=r.get("net_oos_MLOFI"),
                                     fees_bps=fee_bps, verdict=r.get("verdict", "MORE_DATA"))
    pairs = sum(max(0, len(v) - 1) for v in bycoin.values())
    return F.ligne_canonique("MLOFI multi-niveaux", config_frozen="top5", data="metaorder top5", event="MLOFI",
                             verdict="MORE_DATA", n_raw=pairs, notes="tape trop court: %d paires top5, aucun coin>=60" % pairs)


def _adapt_leadlag(data_dir: str, fee_bps: float) -> dict[str, Any]:
    try:
        from hl_observer.research import hl_binance_leadlag as _ll
    except Exception:
        return _blocked("lead_lag", "module hl_binance_leadlag indisponible")
    for name in ("_alpha_leadlag_big.csv", "_alpha_leadlag_extract.csv"):
        path = os.path.join(data_dir, name)
        if not _existe(path):
            continue
        series = _ll.charger_series(path)
        if not series:
            continue
        coin = max(series, key=lambda c: len(series[c]))
        r = _ll.experience(series[coin], cout_bps=fee_bps)
        return F.ligne_canonique("Lead-lag HL<-Binance (%s)" % coin, config_frozen="choc>=seuil gele; DISC/OOS",
                                 data=name, event="Binance move", execution="TAKER/TAKER",
                                 n_independent=r.get("n_independent_oos"), gross_bps=r.get("gross_bps_oos"),
                                 fees_bps=fee_bps, net_bps=r.get("net_bps_oos"), lcb_net_bps=r.get("lcb_net_bps"),
                                 verdict=r.get("verdict", "MORE_DATA"), notes="peak_lag=%s" % r.get("peak_lag"))
    return _blocked("lead_lag", "extrait _alpha_leadlag_*.csv absent")


def _adapt_anticipation(data_dir: str, fee_bps: float) -> dict[str, Any]:
    bbo = os.path.join(data_dir, "bbo_synchro.jsonl")
    fills = os.path.join(data_dir, "leader_fills_forward.jsonl")
    if not (_existe(bbo) and _existe(fills)):
        return _blocked("wallet_binance_anticipation", "bbo_synchro.jsonl (HL+Binance simultane) absent")
    bin_by_coin = _wba.charger_bin_series(bbo, {"BTC", "ETH", "SOL"}, max_lignes=600000)
    r = _wba.experience_anticipation(_wba.charger_fills(fills), bin_by_coin, horizon_ms=5000, cout_bps=fee_bps)
    best = r["classement"][0] if r["classement"] else None
    return F.ligne_canonique("Wallet x Binance anticipation", config_frozen="h=5s; grappes; OOS disjoint",
                             data="bbo_synchro x leader_fills", event="wallet fill vs Binance", execution="TAKER/TAKER",
                             n_independent=(best["n_independent"] if best else U),
                             net_bps=(best["net_after_cout_bps"] if best else U), fees_bps=fee_bps,
                             verdict=(best["verdict"] if best else "MORE_DATA"),
                             notes="%d wallets mesures" % r["n_wallets_mesures"])


def _adapt_cross_venue(data_dir: str, fee_bps: float) -> dict[str, Any]:
    bbo = os.path.join(data_dir, "bbo_synchro.jsonl")
    if not _existe(bbo):
        return _blocked("cross_venue", "bbo_synchro.jsonl absent (edge exec + desync non calculables)")
    # mesure legere sur echantillon frais (desync<50ms), BTC
    edges = []
    n = 0
    with open(bbo, encoding="utf-8") as f:
        for line in f:
            if n > 300000:
                break
            n += 1
            try:
                x = json.loads(line)
            except Exception:
                continue
            if x.get("coin") != "BTC" or abs(x.get("desync_ms", 1e9)) > 50:
                continue
            mid = x.get("hl_mid")
            if not mid:
                continue
            e = max(x["bin_bid"] - x["hl_ask"], x["hl_bid"] - x["bin_ask"]) / mid * 1e4
            edges.append(e)
    if len(edges) < 500:
        return _blocked("cross_venue", "trop peu de snapshots BTC frais (%d)" % len(edges))
    edges.sort()
    p99 = edges[int(0.99 * len(edges))]
    net = p99 - fee_bps
    return F.ligne_canonique("Cross-venue latency arb (BTC, fresh)", config_frozen="desync<50ms; edge exec 2-jambes",
                             data="bbo_synchro", event="dislocation", state="fresh", execution="TAKER/TAKER",
                             n_raw=len(edges), gross_bps=round(p99, 4), fees_bps=fee_bps, net_bps=round(net, 4),
                             verdict=("KILL" if net <= 0 else "MORE_DATA"),
                             notes="P99 edge exec=%.2f bps ; gross<=P95 cout => KILL" % p99)


# famille -> adaptateur (ou None = BLOCKED avec raison generique)
ADAPTERS = {
    "ofi_microstructure": _adapt_ofi,
    "copy_population": _adapt_population,
    "copy_wallet": _adapt_population,
    "mlofi": _adapt_mlofi,
    "lead_lag": _adapt_leadlag,
    "wallet_binance_anticipation": _adapt_anticipation,
    "cross_venue": _adapt_cross_venue,
    "twap_metaorder": _adapt_mlofi,   # meme tape metaorder (residual/hazard) — mesure honnete MORE_DATA
}
RAISONS_BLOCKED = {
    "maker_execution": "signaux a gross prometteur + queue/trade-through reels requis",
    "liquidations_triggers": "flux de liquidations/triggers absent (SHADOW)",
    "exits": "chemins de markout par strategie requis (depend d'un signal survivant)",
    "multi_venue": "flux read-only Bybit/OKX/Coinbase absent",
    "l4_intent": "flux node/L4 (ORDER/MODIFY/CANCEL/FILL) absent",
    "hf_data": "capture live HL+Binance cote user (pas de reseau ici)",
}


def run_all(*, data_dir: str, registry_path: str, fee_bps: float = 9.0, reset: bool = False) -> dict[str, Any]:
    """Exécute TOUTES les familles du registre via leur adaptateur → un trial ou un BLOCKED précis chacune."""
    reg = F.TrialRegistry(registry_path)
    if reset:
        open(registry_path, "w").close()
    familles = list(_fam.FAMILLES)
    rows: list[dict[str, Any]] = []
    for fam in familles:
        adapter = ADAPTERS.get(fam)
        try:
            if adapter is not None:
                row = adapter(data_dir, fee_bps)
            else:
                row = _blocked(fam, RAISONS_BLOCKED.get(fam, "adaptateur absent"))
        except Exception as exc:                      # une famille qui casse ne casse pas le run
            row = F.ligne_canonique("[%s] ERREUR" % fam, config_frozen="—", verdict="ERROR", notes=str(exc)[:160])
        row["_famille"] = fam
        rows.append(row)
    for r in rows:
        reg.record(r)
    familles_couvertes = {r["_famille"] for r in rows}
    return {"n_trials": len(rows), "rows": rows, "table": F.emit_table(rows),
            "familles_couvertes": sorted(familles_couvertes),
            "n_familles": len(familles)}


__all__ = ["run_all", "ADAPTERS", "RAISONS_BLOCKED"]
