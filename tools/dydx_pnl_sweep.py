#!/usr/bin/env python3
"""
Outil de sélection data-driven pour viser un PnL paper positif — READ-ONLY.

Principe honnête: avant de copier un wallet, on vérifie qu'il gagne sur SES
PROPRES trades. On rejoue les fills historiques dans le backtester dYdX
(`DydxBacktester.run_on_fills`) et on classe wallets et marchés par PnL net.

Règle: si un leader est déjà net-négatif sur ses propres prix d'entrée/sortie,
le copier est sans espoir (notre copie n'ajoute que des coûts). On ne garde que
les wallets net-positifs, à winrate et échantillon suffisants.

⚠️ Le backtester utilise les PRIX DU LEADER (cas optimiste, frais seulement).
   Un PnL backtest positif est NÉCESSAIRE mais pas SUFFISANT: en live la copie
   ajoute latence + spread + slippage. Traiter ce classement comme un FILTRE
   d'élimination (jeter les perdants), pas comme une promesse de gain.

Usage:
    python tools/dydx_pnl_sweep.py                       # jeu de DÉMO illustratif
    python tools/dydx_pnl_sweep.py --fills mes_fills.jsonl
    python tools/dydx_pnl_sweep.py --fills f.jsonl --min-trades 10 --json out.json

Format JSONL attendu (un objet par ligne):
    {"fill_id","account_address","subaccount_number","market_id",
     "side":"BUY|SELL","size","price","fee","created_at_ms"}

PAPER/BACKTEST uniquement. Aucun ordre réel, aucune clé, aucune signature.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Import du module dYdX (repo root sur le path)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from hyper_smart_observer.dydx_v4.backtest import DydxBacktester  # noqa: E402
from hyper_smart_observer.dydx_v4.config import DydxV4Config  # noqa: E402
from hyper_smart_observer.dydx_v4.models import (  # noqa: E402
    NormalizedFill,
    OrderSide,
    SimulationMode,
)

LIQUID_MARKETS = {"BTC-USD", "ETH-USD", "SOL-USD"}


def _order_side(value: str) -> OrderSide:
    v = str(value).strip().upper()
    try:
        return OrderSide(v)
    except ValueError:
        # repli défensif
        return OrderSide("BUY") if v == "BUY" else OrderSide("SELL")


def fill_from_dict(d: dict) -> NormalizedFill | None:
    try:
        return NormalizedFill(
            fill_id=str(d["fill_id"]),
            account_address=str(d["account_address"]),
            subaccount_number=int(d.get("subaccount_number", 0)),
            market_id=str(d["market_id"]),
            side=_order_side(d["side"]),
            size=float(d["size"]),
            price=float(d["price"]),
            fee=float(d.get("fee", 0.0)),
            liquidity=str(d.get("liquidity", "TAKER")),
            created_at_ms=int(d["created_at_ms"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


def load_fills(path: str) -> list[NormalizedFill]:
    fills: list[NormalizedFill] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            f = fill_from_dict(d)
            if f is not None:
                fills.append(f)
    return fills


def demo_fills() -> list[NormalizedFill]:
    """Jeu illustratif: W1 gagne (BTC), W3 gagne peu (SOL), W2 perd (ETH)."""
    def mk(fid, addr, mkt, side, size, price, t):
        notional = size * price
        return NormalizedFill(
            fill_id=fid, account_address=addr, subaccount_number=0,
            market_id=mkt, side=_order_side(side), size=size, price=price,
            fee=notional * 5 / 10_000, liquidity="TAKER", created_at_ms=t,
        )
    w1 = "dydx1winnerbtc000000000000000000000000aa"
    w2 = "dydx1loosereth00000000000000000000000bb"
    w3 = "dydx1smallwinsol0000000000000000000000cc"
    return [
        mk("w1-1", w1, "BTC-USD", "BUY", 0.10, 60000, 1000),
        mk("w1-2", w1, "BTC-USD", "SELL", 0.10, 61000, 2000),   # +100 brut
        mk("w2-1", w2, "ETH-USD", "BUY", 1.00, 3000, 1100),
        mk("w2-2", w2, "ETH-USD", "SELL", 1.00, 2950, 2100),    # -50 brut
        mk("w3-1", w3, "SOL-USD", "BUY", 10.0, 150, 1200),
        mk("w3-2", w3, "SOL-USD", "SELL", 10.0, 151, 2200),     # +10 brut
        mk("w2-3", w2, "HYPE-USD", "BUY", 5.0, 40, 1300),
        mk("w2-4", w2, "HYPE-USD", "SELL", 5.0, 39, 2300),      # -5 brut (illiquide)
    ]


def run_subset(fills: list[NormalizedFill], fee_bps: float) -> dict:
    cfg = DydxV4Config()
    bt = DydxBacktester(cfg)
    res = bt.run_on_fills(fills, mode=SimulationMode.BACKTEST, fee_bps=fee_bps)
    return {
        "trades": res.total_trades,
        "net_pnl": round(res.net_pnl, 4),
        "gross_pnl": round(res.gross_pnl, 4),
        "fees": round(res.total_fees, 4),
        "winrate": round(res.winrate, 3) if res.winrate is not None else None,
        "max_drawdown": round(res.max_drawdown, 4),
    }


def group_by(fills, key_fn):
    out: dict[str, list] = {}
    for f in fills:
        out.setdefault(key_fn(f), []).append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Classement wallets/marchés par PnL net (backtest, READ-ONLY)")
    ap.add_argument("--fills", help="JSONL de fills historiques (sinon: démo)")
    ap.add_argument("--fee-bps", type=float, default=5.0, help="frais taker bps (défaut 5)")
    ap.add_argument("--min-trades", type=int, default=4, help="trades min pour shortlister un wallet")
    ap.add_argument("--min-winrate", type=float, default=0.5, help="winrate min pour shortlister")
    ap.add_argument("--json", help="écrire le rapport JSON ici")
    args = ap.parse_args()

    if args.fills:
        fills = load_fills(args.fills)
        source = args.fills
    else:
        fills = demo_fills()
        source = "DÉMO (illustratif — fournir --fills pour de vraies conclusions)"

    if not fills:
        print("Aucun fill exploitable. Vérifier le format JSONL.")
        return 1

    print("=" * 72)
    print("dYdX PnL Sweep — classement data-driven (BACKTEST, READ-ONLY, PAPER)")
    print(f"Source: {source}")
    print(f"Fills: {len(fills)} | fee_bps={args.fee_bps}")
    print("=" * 72)

    overall = run_subset(fills, args.fee_bps)
    print(f"\n[GLOBAL] net_pnl={overall['net_pnl']} | trades={overall['trades']} "
          f"| winrate={overall['winrate']} | fees={overall['fees']}")

    # -- Sensibilité aux coûts (les frais mangent le PnL) -------------------- #
    print("\n[SENSIBILITÉ COÛTS] net_pnl selon fee_bps:")
    for fb in (5.0, 10.0, 15.0):
        r = run_subset(fills, fb)
        print(f"   fee={fb:>4} bps -> net_pnl={r['net_pnl']:>10} (trades fermés {r['trades']})")

    # -- Par wallet ---------------------------------------------------------- #
    per_wallet = []
    for addr, wf in group_by(fills, lambda f: f.account_address).items():
        r = run_subset(wf, args.fee_bps)
        per_wallet.append((addr, r))
    per_wallet.sort(key=lambda x: x[1]["net_pnl"], reverse=True)

    print("\n[PAR WALLET] (trié par net_pnl):")
    for addr, r in per_wallet:
        tag = "✅ GARDER" if (r["net_pnl"] > 0 and (r["winrate"] or 0) >= args.min_winrate
                              and r["trades"] >= args.min_trades) else "⛔ JETER"
        print(f"   {addr[:18]}… net={r['net_pnl']:>9} winrate={r['winrate']} "
              f"trades={r['trades']}  {tag}")

    shortlist = [
        addr for addr, r in per_wallet
        if r["net_pnl"] > 0 and (r["winrate"] or 0) >= args.min_winrate
        and r["trades"] >= args.min_trades
    ]

    # -- Par marché ---------------------------------------------------------- #
    per_market = []
    for mkt, mf in group_by(fills, lambda f: f.market_id).items():
        r = run_subset(mf, args.fee_bps)
        per_market.append((mkt, r))
    per_market.sort(key=lambda x: x[1]["net_pnl"], reverse=True)

    print("\n[PAR MARCHÉ] (trié par net_pnl):")
    for mkt, r in per_market:
        liq = "liquide" if mkt in LIQUID_MARKETS else "ILLIQUIDE→éviter"
        print(f"   {mkt:<12} net={r['net_pnl']:>9} winrate={r['winrate']} trades={r['trades']}  ({liq})")

    print("\n" + "-" * 72)
    print(f"RECOMMANDATION shortlist ({len(shortlist)} wallets net-positifs, "
          f"winrate≥{args.min_winrate}, trades≥{args.min_trades}):")
    for a in shortlist:
        print(f"   {a}")
    if not shortlist:
        print("   (aucun) — sur ces données, AUCUN wallet n'est assez rentable: NE PAS COPIER.")
    print("\n⚠️ Backtest = prix du leader, frais seulement. NÉCESSAIRE mais pas")
    print("   suffisant: en live, latence+spread+slippage réduisent encore le PnL.")
    print("   N'utiliser ce classement que pour ÉLIMINER les wallets perdants.")
    print("   Aucun ordre réel, aucune clé, aucune signature. PAPER/BACKTEST only.")

    if args.json:
        report = {
            "source": source,
            "overall": overall,
            "per_wallet": [{"address": a, **r} for a, r in per_wallet],
            "per_market": [{"market": m, **r} for m, r in per_market],
            "shortlist": shortlist,
            "disclaimer": "BACKTEST READ-ONLY. No real orders. Past != future.",
        }
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nRapport JSON écrit: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
