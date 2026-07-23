"""Tick EXPLORATORY_PAPER (--une-fois, pour boucle_collecteur) — cohorte d'apprentissage isolée.

Ouvre de vraies positions PAPER sur les mouvements LIVE des vaults retenus, gatées par un edge
PRÉLIMINAIRE positif (copy_prelim_edge.json), L2 <1 s, VWAP, coûts complets, sortie définie (leader/
stop/horizon). Budget $300, max 3 positions, pertes plafonnées. Gaté par HYPERSMART_EXPLORATORY_PAPER=1.
PAPER-only : aucun ordre réel, aucune signature. Aucun signal synthétique, aucun trade forcé."""
from __future__ import annotations

import argparse
import json
import os

from hl_observer.experimental.exploratoire import tick


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tick EXPLORATORY_PAPER (paper-only).")
    p.add_argument("--root", default=".")
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    if os.environ.get("HYPERSMART_EXPLORATORY_PAPER", "0") != "1":
        print("[exploratoire] DESACTIVE (HYPERSMART_EXPLORATORY_PAPER != 1)", flush=True)
        return 0
    r = tick(a.root)
    st = r["statut"]
    print("[exploratoire] ouvertures=%d fermetures=%d positions=%d equity=%.2f$ ROI=%.2f%% coins_prelim+=%d refus=%s"
          % (len(r["ouvertures"]), len(r["fermetures"]), st["positions_ouvertes"], st["equity_usd"],
             st["roi_cumulatif_pct"], st["n_coins_prelim_positifs"], json.dumps(r["refus_par_motif"])), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
