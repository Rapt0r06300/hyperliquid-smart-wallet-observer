"""VOIR L'ETAT DU CARRY (paper, lecture seule) -> une vue simple et lisible pour Flo.

Lit runtime/data/carry_spot_shortlist.json (coins viables), carry_paper_positions.json (positions
ouvertes) et carry_paper_ledger.jsonl (PnL realise) et l'affiche en clair. N'ecrit RIEN, ne trade
RIEN : 100% lecture. Double-clique VOIR-CARRY.cmd pour l'ouvrir.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hl_observer.funding.carry_positions_store import etat_carry, charger_gestionnaire  # noqa: E402

DATA = ROOT / "runtime" / "data"


def _charge(nom):
    try:
        return json.loads((DATA / nom).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _age(ms, now_ms):
    h = (now_ms - float(ms)) / 3.6e6
    if h < 1:
        return "%d min" % round(h * 60)
    if h < 48:
        return "%.1f h" % h
    return "%.1f j" % (h / 24)


def main() -> int:
    now = time.time() * 1000
    print("=" * 64)
    print("  ETAT DU CARRY  (paper, lecture seule -- aucun ordre reel)")
    print("=" * 64)

    sl = _charge("carry_spot_shortlist.json")
    if isinstance(sl, list) and sl:
        print("\n  COINS VIABLES mesures (%d) :" % len(sl))
        for x in sl:
            print("    - %-6s funding %+.3f bps/h | base %+.2f bps | liq $%-8.0f | levier %gx"
                  % (x.get("coin", "?"), x.get("funding_bps_h", 0), x.get("base_bps", 0),
                     x.get("liquidite_spot_usd", 0), x.get("levier_utilise", 0)))
    else:
        print("\n  Aucun coin viable mesure pour l'instant (funding bas / spot mince).")

    g = charger_gestionnaire(ROOT)
    print("\n  POSITIONS OUVERTES (%d) :" % len(g.ouvertes))
    accru = 0.0
    for c, p in g.ouvertes.items():
        accru += float(p.get("funding_accrued_usdt") or 0.0)
        print("    - %-6s notional $%-6.0f | funding accru $%.4f | ouvert depuis %s"
              % (c, p.get("notional_usdt", 0), p.get("funding_accrued_usdt", 0),
                 _age(p.get("entry_ts_ms", now), now)))
    if not g.ouvertes:
        print("    (aucune)")

    etat = etat_carry(ROOT)
    print("\n  " + "-" * 60)
    print("  PnL REALISE cumule (positions fermees) : $%.4f" % etat["realized_net_pnl_usdc"])
    print("  Funding ACCRU (ouvert, pas encore realise) : $%.4f" % round(accru, 4))
    print("  Ouvertures: %d | Fermetures: %d" % (etat["opens"], etat["closes"]))
    print("\n  Note : le carry est LENT (break-even ~jours). Un funding qui s'accumule")
    print("  chaque heure + un PnL realise a la fermeture = c'est NORMAL et honnete.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
