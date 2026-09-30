"""BOT-READY — imprime le score de maturité du bot + le niveau d'autonomie SÛR.

Porté de `cobusgreyling/loop-engineering` (loop-audit), lentille TRADING. Ce CLI est un mince
wrapper : toute la logique (parsing du RECAP, dérivation deny-by-default, barème, échelle
d'autonomie) vit dans `hl_observer.ops.loop_readiness` — source unique, appelée aussi par le
lanceur. Un signal introuvable est compté 0 (deny-by-default), jamais supposé vert.

    python tools/bot_ready.py            # imprime le bloc BOT-READY
    python tools/bot_ready.py --ecrire   # + l'ajoute à BOT_READY.md à la racine

Lecture seule, aucun réseau, aucun ordre. Un score n'autorise jamais rien : le plafond de
l'échelle est le testnet verrouillé ; le trading réel est hors échelle (voir loop_readiness).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import loop_readiness as LR  # noqa: E402


def collecter(racine: Path | str = RACINE) -> LR.RapportReadiness:
    """Le score dérivé du dernier RECAP (délégué à la source unique loop_readiness)."""
    return LR.depuis_le_recap(racine)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score de maturité du bot (lecture seule).")
    ap.add_argument("--racine", default=str(RACINE))
    ap.add_argument("--ecrire", action="store_true", help="écrit aussi BOT_READY.md")
    a = ap.parse_args(argv)
    racine = Path(a.racine)
    rap = collecter(racine)
    bloc = LR.markdown(rap)
    print(bloc)
    non_prouves = [c for c in ("pnl_reconcilie", "portes_cout_actives", "kill_switch_cable")
                   if rap.dimensions.get(c, {}).get("score", 0) == 0]
    if non_prouves:
        print("\n_Signaux non prouvés depuis le seul RECAP (comptés 0, deny-by-default) : %s._"
              % ", ".join(non_prouves))
    if a.ecrire:
        (racine / "BOT_READY.md").write_text(bloc + "\n", encoding="utf-8")
        print("\n-> BOT_READY.md écrit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
