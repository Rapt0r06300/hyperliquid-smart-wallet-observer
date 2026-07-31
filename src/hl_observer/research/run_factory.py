"""ALPHA FACTORY — PIPELINE exécutable : charge la donnée présente, lance TOUTES les expériences mesurables,
loggue chaque essai au registre global, émet la table canonique. Une fonction = la table à jour.

Robuste : chaque source absente → ligne `BLOCKED_EXTERNAL` (jamais de crash, jamais de 0 inventé). Ré-exécutable
tel quel : dès qu'une des collectes manquantes arrive dans `data_dir`, la ligne passe de BLOCKED à mesurée.

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import os
from typing import Any

from hl_observer.research import alpha_factory as F
from hl_observer.research import mlofi as _ml
from hl_observer.research import ofi_microprice as _ofi
from hl_observer.research import order_intent as _oi
from hl_observer.research import wallet_population as _wp

U = F.UNMEASURABLE


def _existe(path: str) -> bool:
    return bool(path) and os.path.exists(path)


def _experience_ofi(data_dir: str, coin: str, fee_bps: float) -> dict[str, Any]:
    path = os.path.join(data_dir, "_ofi_%s.csv" % coin)
    if not _existe(path):
        return F.ligne_canonique("OFI/microprice %s" % coin, config_frozen="l2_book %s" % coin,
                                 verdict="BLOCKED_EXTERNAL", data="l2_book absent", notes="fichier _ofi_%s.csv absent" % coin)
    d = _ofi.charger_book_csv(path)
    serie = d.get(coin, [])
    if len(serie) < 500:
        return F.ligne_canonique("OFI/microprice %s" % coin, config_frozen="l2_book %s" % coin,
                                 verdict="MORE_DATA", n_raw=len(serie), data="l2_book %s" % coin)
    r = _ofi.experience_complete(serie, coin=coin, horizon_pas=2, fee_bps=fee_bps)
    best = min((v for v in r["par_feature"].values() if isinstance(v.get("net_bps_oos"), (int, float))),
              key=lambda v: v["net_bps_oos"], default=None)
    net = best["net_bps_oos"] if best else U
    lcb = best["lcb_net_bps"] if best else U
    verdict = best["verdict"] if best else "MORE_DATA"
    return F.ligne_canonique("OFI/microprice %s (best)" % coin,
                             config_frozen="l2_book; DISC->FREEZE->OOS; h=2", data="l2_book %s" % coin,
                             event="imbalance/OFI/micro", state="—", horizon="~36s", execution="TAKER/TAKER",
                             n_independent=(best.get("n_votes_independants") if best else U),
                             gross_bps=(best.get("gross_bps_oos") if best else U), fees_bps=fee_bps,
                             net_bps=net, lcb_net_bps=lcb, oos="net<0" if isinstance(net, (int, float)) and net < 0 else "—",
                             capacity_usd=U, verdict=verdict,
                             notes="contemp R2=%s" % r["diagnostic_ofi_contemporain"].get("r2"))


def _experience_population(data_dir: str, fee_bps: float) -> dict[str, Any]:
    path = os.path.join(data_dir, "leader_fills_forward.jsonl")
    if not _existe(path):
        return F.ligne_canonique("Wallet population", config_frozen="net copyable edge",
                                 verdict="BLOCKED_EXTERNAL", data="leader_fills absent")
    out = _wp.classer_population(path, cout_bps=fee_bps, min_fills=8)
    cand = [l for l in out["classement"] if l.get("verdict") in ("CANDIDAT", "FORWARD_REQUIS")]
    return F.ligne_canonique("Wallet population (%d wallets)" % out["n_evalues"],
                             config_frozen="grappes wallet:coin:jour; classe par net edge",
                             data="leader_fills_forward", event="wallet fills", execution="TAKER/TAKER",
                             n_raw=out["n_lignes_streamees"], fees_bps=fee_bps, net_bps=U, lcb_net_bps=U,
                             capacity_usd=U, verdict=("CANDIDAT" if cand else "KILL"),
                             notes="%d candidats ; %d clusters d'entite" % (len(cand), out["n_clusters_entite"]))


def _experience_mlofi(data_dir: str, fee_bps: float) -> dict[str, Any]:
    import json
    import collections
    path = os.path.join(data_dir, "metaorder_l2_tape.jsonl")
    if not _existe(path):
        return F.ligne_canonique("MLOFI multi-niveaux", config_frozen="top5; L1/L3/L5",
                                 verdict="BLOCKED_EXTERNAL", data="metaorder tape absent")
    bycoin: dict[str, list] = collections.defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("top5")
            if t and t.get("bids") and t.get("asks") and d.get("coin") and d.get("fill_time"):
                bycoin[d["coin"]].append((d["fill_time"], t))
    best = None
    for coin, seq in bycoin.items():
        seq.sort(key=lambda x: x[0])
        books = [t for _, t in seq]
        if len(books) >= 60:
            r = _ml.experience_mlofi(books, niveaux=5, horizon_pas=1, fee_bps=fee_bps)
            best = (coin, r)
            break
    if best is None:
        pairs = sum(max(0, len(v) - 1) for v in bycoin.values())
        return F.ligne_canonique("MLOFI multi-niveaux", config_frozen="top5; L1/L3/L5",
                                 data="metaorder top5", event="MLOFI", verdict="MORE_DATA",
                                 n_raw=pairs, notes="tape 24min: %d paires top5, aucun coin >=60" % pairs)
    coin, r = best
    return F.ligne_canonique("MLOFI multi-niveaux (%s)" % coin, config_frozen="top5; L1/L3/L5; h=1",
                             data="metaorder top5", event="MLOFI", execution="TAKER/TAKER",
                             n_independent=r.get("n_oos_MLOFI"), net_bps=r.get("net_oos_MLOFI"), fees_bps=fee_bps,
                             verdict=r.get("verdict"),
                             notes="incr multi-niveaux=%s ; netL1=%s" % (r.get("increment_multiniveaux_bps"), r.get("net_oos_L1")))


def run_all(*, data_dir: str, registry_path: str, coins_l2: tuple[str, ...] = ("BTC", "ETH", "SOL", "HYPE"),
            fee_bps: float = 9.0, reset: bool = True) -> dict[str, Any]:
    """Lance le pipeline complet et retourne {n_trials, table, rows}."""
    reg = F.TrialRegistry(registry_path)
    if reset:
        open(registry_path, "w").close()
    rows: list[dict[str, Any]] = []

    def _safe(fn, *a):
        try:
            return fn(*a)
        except Exception as exc:  # une expérience qui casse ne casse pas le run
            return F.ligne_canonique("ERREUR %s" % getattr(fn, "__name__", "?"), config_frozen="—",
                                     verdict="ERROR", notes=str(exc)[:160])

    for coin in coins_l2:
        rows.append(_safe(_experience_ofi, data_dir, coin, fee_bps))
    rows.append(_safe(_experience_population, data_dir, fee_bps))
    rows.append(_safe(_experience_mlofi, data_dir, fee_bps))
    rows.append(_oi.experience_intent(None) and F.ligne_canonique(
        "L4 / order-intent", config_frozen="ORDER->..->FILL/CANCEL", data="node/L4 absent",
        verdict="BLOCKED_EXTERNAL", notes="interface prete ; flux L4 a collecter"))

    for r in rows:
        reg.record(r)
    return {"n_trials": len(rows), "rows": rows, "table": F.emit_table(rows)}


__all__ = ["run_all"]
