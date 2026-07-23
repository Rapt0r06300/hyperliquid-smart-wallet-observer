"""Tick EXPERIMENTAL_PAPER (--une-fois, pour boucle_collecteur). Lit les données LIVE, ouvre/gère/sort
les positions paper des 3 moteurs (cross-venue, lead-lag, copy-vaults). Gaté par le flag
HYPERSMART_EXPERIMENTAL_PAPER=1. PAPER-only : aucun ordre réel, aucune signature."""
from __future__ import annotations

import argparse
import json
import os

from hl_observer.experimental.runner import tick


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tick EXPERIMENTAL_PAPER (paper-only).")
    p.add_argument("--root", default=".")
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    if os.environ.get("HYPERSMART_EXPERIMENTAL_PAPER", "0") != "1":
        print("[experimental] DESACTIVE (HYPERSMART_EXPERIMENTAL_PAPER != 1)", flush=True)
        return 0
    st = tick(a.root)
    print("[experimental] ouvertures=%d fermetures=%d positions=%d realise=%.4f$ refus=%d" % (
        len(st["ouvertures"]), len(st["fermetures"]), st["resume"]["positions_ouvertes"],
        st["resume"]["realise_total_usd"], st["n_refus"]), flush=True)
    if st.get("premier_signal"):
        print("[experimental] 1er signal admis:", json.dumps(st["premier_signal"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
