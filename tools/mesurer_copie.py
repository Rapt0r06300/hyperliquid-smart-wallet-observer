"""MESURE RÉELLE DE L'EDGE DE COPIE (rectif Flo 23/07) — tourne sur les vrais fills backfillés.

Chaîne : vault_episodes.jsonl (produit par backfill_vault_fills, réseau) → entrées ALPHA (retraits
exclus) → move_frac via le NAV du vault → tape de prix (hl_allmids_tape) → mesure OOS train→walk-forward
vs placebo → si edge validé OOS, GEL de la config (le signal copy_vault ne consomme QUE ça) + simulation
paper. Écrit copy_edge_rapport.json. NEED_MORE_DATA tant que l'historique est trop court. Aucun ordre.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
from hl_observer.experimental.copy_edge_forward import charger_prix_tape, geler  # noqa: E402
from hl_observer.experimental.copy_edge_oos import mesurer_oos, simuler_paper  # noqa: E402

EPISODES = Path("runtime") / "data" / "vault_episodes.jsonl"
SNAP = Path("runtime") / "data" / "vault_snapshots.jsonl"
RAPPORT = Path("runtime") / "data" / "copy_edge_rapport.json"


def _nav_par_vault(root: Path) -> dict[str, float]:
    """Dernier NAV connu par vault (pour convertir taille_usd -> move_frac)."""
    nav: dict[str, float] = {}
    try:
        for l in (root / SNAP).read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(l)
            except ValueError:
                continue
            v = d.get("vault")
            if v and float(d.get("nav_usd") or 0) > 0:
                nav[v] = float(d["nav_usd"])          # le dernier gagne (fichier chronologique)
    except OSError:
        pass
    return nav


def charger_entrees_alpha(root: Path) -> list[dict]:
    """Entrées alpha (OPEN/ADD hors retrait) avec move_frac = taille_usd / NAV du vault."""
    try:
        lignes = (root / EPISODES).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    episodes = [json.loads(l) for l in lignes if l.strip()]
    nav = _nav_par_vault(root)
    out = []
    for e in VB.entrees_alpha(episodes):
        n = nav.get(e.get("vault"), 0.0)
        if n > 0:
            e = dict(e, move_frac=round(float(e.get("taille_usd") or 0.0) / n, 4))
            out.append(e)
    return out


def construire(root: Path, *, geler_si_valide: bool = True) -> dict:
    entrees = charger_entrees_alpha(root)
    tape = charger_prix_tape(root)
    m = mesurer_oos(entrees, tape)
    rapport = {"maj_ms": int(time.time() * 1000), "n_entrees_alpha": len(entrees),
               "n_coins_tape": len(tape), "mesure": m}
    if m.get("statut") == "MESURE" and m.get("edge_valide_oos"):
        oos = m["oos"]
        sim = simuler_paper(entrees, tape, horizon_ms=oos["horizon_ms"], seuil=oos["seuil"],
                            notional_usd=150.0, cout_ar_bps=m.get("frais_bps", 12.0))
        rapport["simulation_paper_oos"] = sim
        if geler_si_valide:
            rapport["gel"] = geler(root, horizon_ms=oos["horizon_ms"], edge_brut_bps=oos["brut_bps"],
                                   edge_net_mesure_bps=oos["net_bps"], source="mesure_oos_reelle")
    return rapport


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mesure OOS de l'edge de copie (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=1800.0)
    p.add_argument("--une-fois", action="store_true")
    p.add_argument("--pas-de-gel", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    while True:
        rap = construire(root, geler_si_valide=not a.pas_de_gel)
        (root / RAPPORT).write_text(json.dumps(rap, ensure_ascii=False, indent=1), encoding="utf-8")
        m = rap["mesure"]
        extra = ""
        if m.get("statut") == "MESURE":
            extra = " | edge_valide_oos=%s" % m.get("edge_valide_oos")
        print("[mesure-copie] %s  entrees_alpha=%d statut=%s%s"
              % (time.strftime("%H:%M:%S"), rap["n_entrees_alpha"], m.get("statut"), extra), flush=True)
        if a.une_fois:
            return 0
        time.sleep(max(300.0, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
