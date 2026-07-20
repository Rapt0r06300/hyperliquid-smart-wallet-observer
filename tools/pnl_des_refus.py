"""PnL DES REFUS (#43, vague 1) — le coût d'opportunité CHIFFRÉ, plus jamais fantasmé.

Le bot refuse beaucoup (c'est sa discipline). Mais « refuser protège le capital » est une
hypothèse TESTABLE : il suffit de rejouer les candidats REFUSÉS sur les marks réels et de
mesurer ce qu'ils auraient rendu, nets de coûts. Chaque semaine, ce rapport dit :
  * les refus qui nous ont SAUVÉS (PnL simulé négatif -> la porte a bien travaillé) ;
  * les refus qui nous ont COÛTÉ (PnL simulé positif -> la porte est peut-être trop dure,
    et c'est le MOTIF précis qui le dit — pas une impression).
⚠️ Lecture honnête : un refus « coûteux » N'EST PAS une preuve qu'il fallait accepter —
c'est un signal pour RE-MESURER la porte concernée au replay complet (deux moitiés + stress).
Un seul chiffre ne renverse jamais une loi. REPLAY-only, aucun ordre.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.ab_flag_replay import (  # noqa: E402
    DEFAULT_COST_BPS, DEFAULT_HORIZON_MIN, load_jsonl, marks_by_coin, simulate_exit_on_path,
)
from hl_observer.paper_trading.sl_tp import SLTPConfig  # noqa: E402


def pnl_des_refus(root: str | Path = RACINE, *, horizon_min: float = DEFAULT_HORIZON_MIN,
                  cost_bps: float = DEFAULT_COST_BPS,
                  candidats: list | None = None, marks_rows: list | None = None) -> dict:
    """{par_motif: {motif: {n, mesures, pnl_simule_usd}}, total_usd, non_mesurables}."""
    base = Path(root) / "runtime" / "replay"
    cands = candidats if candidats is not None else load_jsonl(str(base / "candidates.jsonl"))
    mrows = marks_rows if marks_rows is not None else load_jsonl(str(base / "marks.jsonl"))
    marks = marks_by_coin(mrows)
    cfg = SLTPConfig(stop_loss_bps=40.0, take_profit_bps=70.0)   # la config de PROD du replay
    par_motif: dict[str, dict] = defaultdict(lambda: {"n": 0, "mesures": 0, "pnl_simule_usd": 0.0})
    total, non_mesurables = 0.0, 0
    for c in cands:
        if not isinstance(c, dict) or c.get("accepte"):
            continue                                    # seuls les REFUS nous interessent ici
        motif = str(c.get("motif") or c.get("reason") or "?")
        e = par_motif[motif]
        e["n"] += 1
        coin = str(c.get("coin") or "").upper()
        mid = c.get("current_mid")
        ts = c.get("recorded_at")
        if not coin or not isinstance(mid, (int, float)) or not isinstance(ts, (int, float)):
            non_mesurables += 1
            continue
        pnl = simulate_exit_on_path(
            side=str(c.get("direction") or "LONG"), entry_price=float(mid),
            path=marks.get(coin, []), entry_ts=float(ts), config=cfg,
            horizon_min=horizon_min, cost_bps=cost_bps)
        if pnl is None:
            non_mesurables += 1
            continue
        e["mesures"] += 1
        e["pnl_simule_usd"] = round(e["pnl_simule_usd"] + pnl, 4)
        total = round(total + pnl, 4)
    return {"par_motif": {k: dict(v) for k, v in sorted(
                par_motif.items(), key=lambda kv: kv[1]["pnl_simule_usd"])},
            "total_usd": total, "non_mesurables": non_mesurables,
            "honnetete": "PnL SIMULE de trades qu'on n'a PAS pris ; un refus couteux = "
                         "re-mesurer la porte au replay complet, jamais l'ouvrir sur ce chiffre",
            "real_execution": False}


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Cout d'opportunite des refus (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    a = p.parse_args(argv)
    r = pnl_des_refus(a.root)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
