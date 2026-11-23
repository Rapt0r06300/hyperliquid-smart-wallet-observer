"""Avant/après capital : la même réplication paper (mêmes données), capital 350 puis 100 USD. Aucune écriture."""
import sys, time, json, dataclasses
from pathlib import Path
R = Path(r"C:/Users/flo/Desktop/Projet invest")
sys.path[:0] = [str(R / "tools"), str(R / "src")]
import etude_copiabilite as E
from hl_observer.backtesting import copy_vault_replication_paper as replication
t0 = time.time()
config = replication.ReplicationConfig()
shards, _ex = E.select_shards(R, {"snapshot": "", "book_l2": "", "allmids": "", "bbo": "", "micro_bbo": "", "asset_ctx": "",
                                  "funding_history": "", "candle": "candles_5m", "position": ""})
identity = E.experiment_identity(R, {k: shards[k] for k in ("snapshot", "book_l2")}, config, "rejeu-capital|mids")
portefeuilles, _rej = replication.portefeuilles_depuis_instantanes(E.load_snapshots(shards["snapshot"]))
panel, tier, refus = E._panneau_de_prix(R, shards, price="mids", stale_ms=120_000, identity=identity)
if refus is not None:
    print("REFUS", json.dumps(refus)[:300]); raise SystemExit(2)
spreads = E.load_half_spreads(E.spread_shards(shards))
funding = E.cop.build_funding_rates(E.load_funding(E.funding_shards(shards)), panel)
print(f"donnees : {len(portefeuilles)} comptes, panneau {tier}, {time.time()-t0:.0f} s")
for capital in (350.0, 100.0):
    cfg = dataclasses.replace(config, capital_usd=capital)
    par = {c: replication.decomposer_les_pertes(p, panel, spreads, cfg, funding_rates=funding)
           for c, p in portefeuilles.items() if len(p) >= 50}
    s = replication.synthese_replication(par, cfg)
    refuses = sum(int(r["full"].get("orders_refused_by_venue_minimum") or 0) for r in par.values())
    ordres = sum(int(r["full"].get("orders") or 0) for r in par.values())
    print(f"CAPITAL {capital:.0f} USD | leaders {len(par)} | net {s.get('net_usd_per_day')} USD/j | IC {s.get('interval_95')}"
          f" | net {s.get('net_bps_per_day_on_capital')} bps/j du capital | ordres {ordres} dont refuses par l'ordre minimal {refuses}"
          f" ({100*refuses/max(1,ordres+refuses):.1f} %)")
print(f"duree {time.time()-t0:.0f} s")
