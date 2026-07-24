"""WATCHER LÉGER — rapport du PREMIER vrai OPEN/CLOSE RAW_PROBE (rectif Flo 23/07).

PUR : lit `raw_probe_ledger.jsonl` et met en forme, pour la 1ʳᵉ paire ouverte : timestamps monotones,
prix/VWAP L2, coûts, MFE/MAE, PnL, ROI, paire vault+coin. Écrit `runtime/rapports/PREMIER_RAW.md`.
Aucun réseau, aucune écriture d'ordre — lecture seule d'un ledger paper (real_execution=false).
"""
from __future__ import annotations

import json
from pathlib import Path

LEDGER_RELPATH = Path("runtime") / "data" / "raw_probe_ledger.jsonl"
RAPPORT_RELPATH = Path("runtime") / "rapports" / "PREMIER_RAW.md"


def _evenements(root: str | Path) -> list[dict]:
    try:
        lignes = (Path(root) / LEDGER_RELPATH).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    out = []
    for l in lignes:
        if l.strip():
            try:
                out.append(json.loads(l))
            except ValueError:
                continue
    return out


def premier_open_close(root: str | Path) -> tuple[dict | None, dict | None]:
    """(1er OPEN, 1er CLOSE de LA MÊME paire) ou (open, None) si encore ouvert, ou (None, None) si rien."""
    evs = _evenements(root)
    op = next((e for e in evs if e.get("evt") == "OPEN"), None)
    if not op:
        return None, None
    cl = next((e for e in evs if e.get("evt") == "CLOSE"
               and e.get("coin") == op.get("coin") and e.get("vault") == op.get("vault")), None)
    return op, cl


def construire_rapport(root: str | Path) -> str | None:
    """Markdown du 1er OPEN (+ CLOSE si dispo). None tant qu'aucun OPEN RAW réel n'existe (jamais inventé)."""
    op, cl = premier_open_close(root)
    if not op:
        return None
    lm = op.get("latences_mono") or {}
    L = ["# Premier RAW_PROBE — OPEN/CLOSE réel (paper, NON_VALIDÉE)", "",
         "## OUVERTURE — paire %s (%s)" % (op.get("paire"), op.get("coin")),
         "- vault : %s" % op.get("vault"),
         "- sens : %s · notional %s $" % ("LONG" if int(op.get("sens") or 0) > 0 else "SHORT", op.get("notional_usd")),
         "- prix d'entrée (L2) : %s · source L2 : %s" % (op.get("prix_entree"), op.get("src_l2")),
         "- edge estimé : %s (RAW = NON_VALIDÉE, aucun edge requis)" % op.get("edge_net_bps"),
         "- latences monotones (ms) : WS→déc %s · déc→L2 %s · L2→open %s · WS→open %s" % (
             lm.get("ws_decision_ms"), lm.get("decision_l2_ms"), lm.get("l2_open_ms"), lm.get("ws_open_ms")),
         "- âge événement à la décision (skew HL possible) : %s ms" % lm.get("age_event_ms"),
         "- **âge RÉEL à l'exécution paper (total fill→open)** : %s ms" % lm.get("age_at_paper_fill_ms"),
         "- cycle_id : %s · open_run_id : %s · trigger_version : %s · statut : %s" % (
             op.get("cycle_id"), op.get("open_run_id") or op.get("run_id"), op.get("trigger_version"), op.get("statut")), ""]
    if cl:
        notional = float(op.get("notional_usd") or 0.0) or 1.0
        roi = float(cl.get("realized_usd") or 0.0) / notional * 100.0
        L += ["## CLÔTURE — %s" % cl.get("raison"),
              "- cycle_id : %s · open_run_id → close_run_id : %s → %s (le cycle traverse les redémarrages)" % (
                  cl.get("cycle_id"), cl.get("open_run_id"), cl.get("close_run_id")),
              "- prix de sortie : %s · trigger_version (stockée à l'OPEN) : %s" % (cl.get("prix_sortie"), cl.get("trigger_version")),
              "- MFE / MAE (bps) : %s / %s" % (cl.get("mfe_bps"), cl.get("mae_bps")),
              "- PnL réalisé : %s $ · ROI : %s %%" % (cl.get("realized_usd"), round(roi, 3)),
              "- PLACEBO même coin/instant : ret_coin %s bps · ret_marché(BTC) %s bps · placebo %s bps · "
              "**alpha vs marché %s bps**" % (cl.get("ret_coin_bps"), cl.get("ret_marche_bps"),
                                              cl.get("placebo_marche_bps"), cl.get("alpha_vs_marche_bps")), ""]
    else:
        L += ["## CLÔTURE", "- position encore OUVERTE (pas de close du leader pour l'instant)", ""]
    L += ["_Sécurité : paper only · real_execution=false · 0 ordre réel · 0 clé · 0 signature._"]
    return "\n".join(L)


def ecrire_rapport(root: str | Path) -> Path | None:
    """Écrit le rapport si un 1er OPEN RAW existe ; rend le chemin, ou None (rien à rapporter encore)."""
    txt = construire_rapport(root)
    if txt is None:
        return None
    p = Path(root) / RAPPORT_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(txt, encoding="utf-8")
    tmp.replace(p)
    return p


__all__ = ["premier_open_close", "construire_rapport", "ecrire_rapport", "LEDGER_RELPATH", "RAPPORT_RELPATH"]
