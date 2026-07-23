"""Fermeture PROPRE + mise en SHADOW du carry historique (decision Flo 2026-07-23).

Ce carry delta-neutre HL-only affichait -8,24 $ : 100 % du funding au PLANCHER (0,125 bph) -> ~2-3 %
APR net, DOMINE par HLP (15-30 %). Le cross-venue mid-cap le remplace. On ferme donc ses positions
ouvertes aux prix EXECUTABLES courants (base par coin depuis carry_bases_courantes.json), COUTS
COMPLETS (via pnl_realise : frais spot+perp, spread, slippage), l'historique reste au ledger.

READ-ONLY / PAPER-ONLY : aucun ordre reel, aucune signature, real_execution=False. A lancer APRES la
relance (carry desactive dans le lanceur) pour qu'aucun runtime ne rouvre en parallele.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from hl_observer.funding.carry_positions_store import fermer_tout_et_desactiver

BASES_RELPATH = Path("runtime") / "data" / "carry_bases_courantes.json"


def bases_executables(root: Path) -> dict[str, float]:
    """{coin: base_mid_bps} depuis le dernier snapshot de bases (prix executable de sortie). Illisible
    -> {} (le closer retombe sur la base d'entree, conservateur, aucun premium invente)."""
    try:
        d = json.loads((root / BASES_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, float] = {}
    for c, v in (d.get("bases") or {}).items():
        if isinstance(v, dict) and isinstance(v.get("base_mid_bps"), (int, float)):
            out[str(c).upper()] = float(v["base_mid_bps"])
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ferme + met en SHADOW le carry historique (paper, executable).")
    p.add_argument("--root", default=".")
    a = p.parse_args(argv)
    root = Path(a.root)
    r = fermer_tout_et_desactiver(root, bases_courantes=bases_executables(root),
                                  now_ms=int(time.time() * 1000))
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
